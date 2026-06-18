"""OAuth token management for QuickBooks API (refresh_token and authorization_code grants)."""

from __future__ import annotations

import base64
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.adapters.quickbooks.exceptions import (
    QuickBooksAuthError,
    QuickBooksRefreshTokenRequiredError,
    QUICKBOOKS_REFRESH_TOKEN_NOTIFY_MESSAGE,
)
from app.adapters.quickbooks.models import TokenBundle
from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_REDIRECT_URI = (
    "https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl"
)


def _clean_env_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ("'", '"'):
        cleaned = cleaned[1:-1].strip()
    return cleaned or None


def _sanitize_oauth_token(value: str) -> str:
    """Strip whitespace/quotes so pasted playground tokens match Postman payloads."""
    import re

    cleaned = _clean_env_value(value) or ""
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned


def _looks_like_access_token(token: str) -> bool:
    return token.startswith("eyJ") or (len(token) > 200 and not token.startswith("RT"))


def _looks_like_refresh_token(token: str) -> bool:
    return token.startswith("RT")


def _oauth_error_hint(exc: QuickBooksAuthError) -> str:
    body = (exc.response_body or str(exc)).lower()
    if "incorrect token type or clientid" in body:
        return (
            "This looks like an access token or a token from a different Intuit app. "
            "Paste the refresh token (starts with RT1-) from the playground **Get Tokens** "
            "response, and ensure QUICKBOOKS_CLIENT_ID in .env matches the playground app."
        )
    if "invalid_grant" in body:
        return (
            "Intuit rejected the token. If you already used this refresh token in Postman, "
            "paste the **new** refresh_token from that response (QuickBooks rotates tokens on "
            "each use). Otherwise generate a fresh token from the playground."
        )
    return str(exc)


def save_quickbooks_credentials_to_env(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    access_token: str | None = None,
    realm_id: str | None = None,
) -> None:
    """Persist QuickBooks app credentials and tokens to .env."""
    from pathlib import Path

    from dotenv import load_dotenv, set_key

    env_path = Path(".env")
    if not env_path.exists():
        logger.warning(".env file not found, cannot save QuickBooks credentials")
        return

    set_key(env_path, "QUICKBOOKS_CLIENT_ID", client_id)
    set_key(env_path, "QUICKBOOKS_CLIENT_SECRET", client_secret)
    set_key(env_path, "QUICKBOOKS_REFRESH_TOKEN", refresh_token)
    if access_token:
        set_key(env_path, "QUICKBOOKS_ACCESS_TOKEN", access_token)
    if realm_id:
        set_key(env_path, "QUICKBOOKS_REALM_ID", realm_id)

    load_dotenv(override=True)
    get_settings.cache_clear()
    logger.info("QuickBooks credentials saved to .env")


class TokenManager:
    """Caches access tokens; refreshes proactively before the 60-minute expiry."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        oauth_url: str,
        refresh_token: str | None = None,
        access_token: str | None = None,
        auth_code: str | None = None,
        redirect_uri: str | None = None,
        refresh_buffer_seconds: int = 300,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not client_id or not client_id.strip():
            raise QuickBooksAuthError("QUICKBOOKS_CLIENT_ID is required")
        if not client_secret or not client_secret.strip():
            raise QuickBooksAuthError("QUICKBOOKS_CLIENT_SECRET is required")

        refresh_token = _clean_env_value(refresh_token)
        access_token = _clean_env_value(access_token)
        auth_code = _clean_env_value(auth_code)
        redirect_uri = _clean_env_value(redirect_uri)

        has_refresh = bool(refresh_token)
        has_auth_code = bool(auth_code)
        if not has_refresh and not has_auth_code and not access_token:
            raise QuickBooksAuthError(
                "QUICKBOOKS_ACCESS_TOKEN, QUICKBOOKS_REFRESH_TOKEN, or "
                "QUICKBOOKS_AUTH_CODE is required"
            )

        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self._oauth_url = oauth_url.strip()
        self._refresh_buffer = timedelta(seconds=refresh_buffer_seconds)
        self._timeout = timeout_seconds
        self._lock = threading.Lock()
        self._token: TokenBundle | None = None
        self._refresh_token = refresh_token if has_refresh else ""
        self._auth_code = auth_code
        self._redirect_uri = redirect_uri or _DEFAULT_REDIRECT_URI

        if access_token:
            self._token = TokenBundle.from_settings(
                access_token=access_token,
                refresh_token=self._refresh_token or None,
            )

    def _basic_auth_header(self) -> str:
        credentials = f"{self._client_id}:{self._client_secret}"
        encoded = base64.standard_b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    def _post_token(self, body: dict[str, str]) -> TokenBundle:
        headers = {
            "Authorization": self._basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        try:
            # WARNING: SSL verification disabled for development
            # For production: install proper certificates or use certifi
            with httpx.Client(timeout=self._timeout, verify=False) as client:
                response = client.post(self._oauth_url, data=body, headers=headers)
        except httpx.HTTPError as exc:
            logger.error("QuickBooks OAuth request failed: %s", exc)
            raise QuickBooksAuthError(f"OAuth request failed: {exc}") from exc

        if response.status_code == 401:
            body_preview = (response.text or "")[:500]
            logger.warning(
                "QuickBooks OAuth 401 grant_type=%s body=%s",
                body.get("grant_type"),
                body_preview,
            )
            raise QuickBooksAuthError(
                "OAuth unauthorized (401); refresh token may be expired",
                status_code=401,
                response_body=body_preview,
            )

        if response.status_code >= 400:
            body_preview = (response.text or "")[:500]
            logger.error(
                "QuickBooks OAuth error status=%s body=%s",
                response.status_code,
                body_preview,
            )
            raise QuickBooksAuthError(
                f"OAuth failed with status {response.status_code}: {body_preview}",
                status_code=response.status_code,
                response_body=body_preview,
            )

        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise QuickBooksAuthError("OAuth response was not valid JSON") from exc

        token = TokenBundle.from_oauth_response(payload)
        if not token.refresh_token:
            previous = self._token.refresh_token if self._token else None
            token.refresh_token = previous

        logger.info("QuickBooks token obtained expires_in=%s", token.expires_in)
        return token

    def _fetch_refresh_token(self, refresh_token: str) -> TokenBundle:
        """Fetch new access token using refresh token. Auto-saves to .env."""
        token = self._post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )

        self._save_tokens_to_env(token)

        if token.refresh_token:
            self._refresh_token = token.refresh_token

        return token

    def _fetch_authorization_code(self, auth_code: str, redirect_uri: str) -> TokenBundle:
        """Exchange a one-time authorization code for access and refresh tokens."""
        token = self._post_token(
            {
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": redirect_uri,
            }
        )

        self._save_tokens_to_env(token)

        if token.refresh_token:
            self._refresh_token = token.refresh_token

        self._clear_auth_code_from_env()

        return token

    @staticmethod
    def _is_refresh_token_error(exc: QuickBooksAuthError) -> bool:
        if exc.status_code not in (400, 401):
            return False
        body = (exc.response_body or "").lower()
        return exc.status_code == 401 or "invalid_grant" in body

    @staticmethod
    def _has_usable_auth_code(auth_code: str | None) -> bool:
        if not auth_code or not auth_code.strip():
            return False
        code = auth_code.strip()
        lowered = code.lower()
        if lowered.startswith("one-time") or lowered.startswith("your-"):
            return False
        return len(code) >= 20

    def _regenerate_via_authorization_code(self) -> TokenBundle:
        if not self._has_usable_auth_code(self._auth_code):
            raise QuickBooksAuthError(
                "Refresh token invalid or expired; set a fresh QUICKBOOKS_AUTH_CODE "
                "from the QuickBooks OAuth playground (single-use, expires in ~5 min)"
            )
        logger.info(
            "QuickBooks exchanging authorization_code for new tokens redirect_uri=%s",
            self._redirect_uri,
        )
        try:
            return self._fetch_authorization_code(self._auth_code, self._redirect_uri)
        except QuickBooksAuthError:
            self._clear_auth_code_from_env()
            raise

    def _try_authorization_code_exchange(self) -> TokenBundle | None:
        if not self._has_usable_auth_code(self._auth_code):
            return None
        try:
            return self._regenerate_via_authorization_code()
        except QuickBooksAuthError as exc:
            logger.warning(
                "QuickBooks authorization_code exchange failed (status=%s): %s",
                exc.status_code,
                exc.response_body or exc,
            )
            return None

    def _try_refresh_token_exchange(self, refresh_token: str) -> TokenBundle | None:
        try:
            return self._fetch_refresh_token(refresh_token)
        except QuickBooksAuthError as exc:
            if not self._is_refresh_token_error(exc):
                raise
            logger.warning(
                "QuickBooks refresh_token failed (status=%s): %s",
                exc.status_code,
                exc.response_body or exc,
            )
            return None
    
    def _save_tokens_to_env(self, token: TokenBundle) -> None:
        """Save refreshed tokens back to .env file automatically."""
        try:
            from pathlib import Path
            from dotenv import set_key
            import os
            
            env_path = Path(".env")
            if not env_path.exists():
                logger.warning(".env file not found, cannot auto-save tokens")
                return
            
            # Save access token
            set_key(env_path, "QUICKBOOKS_ACCESS_TOKEN", token.access_token)
            logger.info("QuickBooks access token auto-saved to .env")

            if token.refresh_token:
                set_key(env_path, "QUICKBOOKS_REFRESH_TOKEN", token.refresh_token)
                logger.info("QuickBooks refresh token auto-saved to .env")
                self._refresh_token = token.refresh_token

            from dotenv import load_dotenv

            load_dotenv(override=True)
            get_settings.cache_clear()

        except Exception as e:
            # Don't fail if we can't save - just log it
            logger.warning(f"Could not auto-save tokens to .env: {str(e)}")

    def _clear_auth_code_from_env(self) -> None:
        """Remove single-use authorization code from .env after successful exchange."""
        try:
            from pathlib import Path

            from dotenv import load_dotenv, set_key

            env_path = Path(".env")
            if not env_path.exists():
                return

            set_key(env_path, "QUICKBOOKS_AUTH_CODE", "")
            load_dotenv(override=True)
            self._auth_code = None
            logger.info("QuickBooks auth code cleared from .env (single-use)")
        except Exception as e:
            logger.warning(f"Could not clear auth code from .env: {str(e)}")

    def _needs_refresh(self, token: TokenBundle) -> bool:
        return datetime.now(timezone.utc) >= token.expires_at - self._refresh_buffer

    def _refresh_locked(self) -> TokenBundle:
        if self._token and not self._needs_refresh(self._token):
            return self._token

        refresh_token = self._token.refresh_token if self._token else self._refresh_token
        if refresh_token:
            token = self._try_refresh_token_exchange(refresh_token)
            if token:
                self._token = token
                return self._token
            self._token = None

        token = self._try_authorization_code_exchange()
        if token:
            self._token = token
            return self._token

        raise QuickBooksRefreshTokenRequiredError()

    def get_valid_token(self) -> TokenBundle:
        with self._lock:
            return self._refresh_locked()

    def force_refresh(self) -> TokenBundle:
        """Discard cached access token and obtain a new one (refresh, then auth code)."""
        with self._lock:
            self._token = None

            refresh_token = self._refresh_token
            if refresh_token:
                token = self._try_refresh_token_exchange(refresh_token)
                if token:
                    self._token = token
                    return self._token

            token = self._try_authorization_code_exchange()
            if token:
                self._token = token
                return self._token

            raise QuickBooksRefreshTokenRequiredError()

    def update_refresh_token(self, refresh_token: str) -> TokenBundle:
        """Validate and persist a new refresh token from the user."""
        cleaned = _sanitize_oauth_token(refresh_token)
        if not cleaned:
            raise QuickBooksAuthError("refresh_token is required")
        if _looks_like_access_token(cleaned):
            raise QuickBooksAuthError(
                "You pasted an access token. Use the refresh token (starts with RT1-)."
            )

        with self._lock:
            self._token = None
            self._refresh_token = cleaned
            token = self._fetch_refresh_token(cleaned)
            self._token = token
            return token

    def exchange_authorization_code(self, auth_code: str) -> TokenBundle:
        """Exchange a playground authorization code and persist tokens."""
        cleaned = _sanitize_oauth_token(auth_code)
        if not cleaned:
            raise QuickBooksAuthError("authorization code is required")

        with self._lock:
            self._token = None
            self._auth_code = cleaned
            token = self._fetch_authorization_code(cleaned, self._redirect_uri)
            self._token = token
            return token

    def invalidate(self) -> None:
        with self._lock:
            if self._token:
                self._token = TokenBundle.from_settings(
                    access_token=self._token.access_token,
                    refresh_token=self._token.refresh_token or self._refresh_token,
                )
