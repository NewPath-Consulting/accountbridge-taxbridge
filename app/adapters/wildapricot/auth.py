"""OAuth token management for WildApricot API (API key / client_credentials)."""

from __future__ import annotations

import base64
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.adapters.wildapricot.exceptions import WildApricotAuthError
from app.adapters.wildapricot.models import TokenBundle

logger = logging.getLogger(__name__)

_TOKEN_BODY_INITIAL = {
    "grant_type": "client_credentials",
    "scope": "auto",
    "obtain_refresh_token": "true",
}


class TokenManager:
    """Caches access tokens; refreshes proactively and on invalidation."""

    def __init__(
        self,
        *,
        api_key: str,
        oauth_url: str,
        refresh_buffer_seconds: int = 300,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key or not api_key.strip():
            raise WildApricotAuthError("WILDAPRICOT_API_KEY is required")
        self._api_key = api_key.strip()
        self._oauth_url = oauth_url.strip()
        self._refresh_buffer = timedelta(seconds=refresh_buffer_seconds)
        self._timeout = timeout_seconds
        self._lock = threading.Lock()
        self._token: TokenBundle | None = None

    def _basic_auth_header(self) -> str:
        credentials = f"APIKEY:{self._api_key}"
        encoded = base64.standard_b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    def _post_token(self, body: dict[str, str]) -> TokenBundle:
        headers = {
            "Authorization": self._basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            # WARNING: SSL verification disabled for development
            # For production: install proper certificates or use certifi
            with httpx.Client(timeout=self._timeout, verify=False) as client:
                response = client.post(self._oauth_url, data=body, headers=headers)
        except httpx.HTTPError as exc:
            logger.error("WildApricot OAuth request failed: %s", exc)
            raise WildApricotAuthError(f"OAuth request failed: {exc}") from exc

        if response.status_code == 401:
            body_preview = (response.text or "")[:500]
            logger.warning(
                "WildApricot OAuth 401 grant_type=%s body=%s",
                body.get("grant_type"),
                body_preview,
            )
            raise WildApricotAuthError(
                "OAuth unauthorized (401); token must be regenerated",
                status_code=401,
                response_body=body_preview,
            )

        if response.status_code >= 400:
            body_preview = (response.text or "")[:500]
            logger.error(
                "WildApricot OAuth error status=%s body=%s",
                response.status_code,
                body_preview,
            )
            raise WildApricotAuthError(
                f"OAuth failed with status {response.status_code}",
                status_code=response.status_code,
                response_body=body_preview,
            )

        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise WildApricotAuthError("OAuth response was not valid JSON") from exc

        token = TokenBundle.from_oauth_response(payload)
        logger.info(
            "WildApricot token obtained expires_in=%s permissions=%s",
            token.expires_in,
            len(token.permissions),
        )
        return token

    def _fetch_client_credentials(self, *, _retried: bool = False) -> TokenBundle:
        try:
            return self._post_token(dict(_TOKEN_BODY_INITIAL))
        except WildApricotAuthError as exc:
            if exc.status_code == 401 and not _retried:
                logger.info("WildApricot OAuth 401; retrying client_credentials once")
                self._token = None
                return self._fetch_client_credentials(_retried=True)
            raise

    def _fetch_refresh_token(self, refresh_token: str) -> TokenBundle:
        return self._post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )

    def _needs_refresh(self, token: TokenBundle) -> bool:
        return datetime.now(timezone.utc) >= token.expires_at - self._refresh_buffer

    def regenerate_token(self) -> TokenBundle:
        """Discard cached token and obtain a new bearer token."""
        with self._lock:
            self._token = None
            self._token = self._fetch_client_credentials()
            return self._token

    def _refresh_locked(self) -> TokenBundle:
        if self._token and not self._needs_refresh(self._token):
            return self._token

        if self._token and self._token.refresh_token:
            try:
                self._token = self._fetch_refresh_token(self._token.refresh_token)
                return self._token
            except WildApricotAuthError as exc:
                logger.warning(
                    "WildApricot refresh_token failed (status=%s); regenerating bearer token",
                    exc.status_code,
                )
                self._token = None

        self._token = self._fetch_client_credentials()
        return self._token

    def get_valid_token(self) -> TokenBundle:
        with self._lock:
            return self._refresh_locked()

    def force_refresh(self) -> TokenBundle:
        """Invalidate cache and obtain a new bearer token (refresh, then client_credentials)."""
        with self._lock:
            refresh_token = self._token.refresh_token if self._token else None
            self._token = None

            if refresh_token:
                try:
                    self._token = self._fetch_refresh_token(refresh_token)
                    return self._token
                except WildApricotAuthError as exc:
                    logger.warning(
                        "WildApricot force_refresh: refresh_token 401/error (status=%s); "
                        "regenerating via client_credentials",
                        exc.status_code,
                    )
                    self._token = None

            self._token = self._fetch_client_credentials()
            return self._token

    def invalidate(self) -> None:
        with self._lock:
            self._token = None

    def resolve_account_id(self, configured_account_id: str | int | None) -> int:
        if configured_account_id not in (None, ""):
            return int(configured_account_id)
        token = self.get_valid_token()
        if not token.permissions:
            raise WildApricotAuthError(
                "WILDAPRICOT_ACCOUNT_ID is not set and token has no Permissions"
            )
        return token.permissions[0].account_id
