"""WildApricot API client facade."""

from __future__ import annotations

import logging
import time
from typing import Any
import warnings

import httpx

# Suppress SSL verification warnings for development
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

from app.adapters.wildapricot.auth import TokenManager
from app.adapters.wildapricot.exceptions import WildApricotAPIError, WildApricotAuthError
from app.adapters.wildapricot.http import parse_json_response
from app.adapters.wildapricot.rate_limit import RequestThrottle, retry_delay_for_429
from app.config.settings import Settings, settings

logger = logging.getLogger(__name__)


class WildApricotClient:
    """Authenticated HTTP client for WildApricot Admin API v2."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        oauth_url: str | None = None,
        api_base_url: str | None = None,
        account_id: str | int | None = None,
        refresh_buffer_seconds: int | None = None,
        timeout_seconds: float | None = None,
        max_requests_per_minute: int | None = None,
        retry_max_attempts: int | None = None,
        retry_429_delay_seconds: float | None = None,
        app_settings: Settings | None = None,
    ) -> None:
        cfg = app_settings or settings
        key = api_key if api_key is not None else cfg.WILDAPRICOT_API_KEY
        self._token_manager = TokenManager(
            api_key=key,
            oauth_url=oauth_url or cfg.WILDAPRICOT_OAUTH_URL,
            refresh_buffer_seconds=refresh_buffer_seconds
            if refresh_buffer_seconds is not None
            else cfg.WILDAPRICOT_TOKEN_REFRESH_BUFFER_SECONDS,
            timeout_seconds=timeout_seconds
            if timeout_seconds is not None
            else cfg.WILDAPRICOT_HTTP_TIMEOUT_SECONDS,
        )
        self._api_base = (api_base_url or cfg.WILDAPRICOT_API_BASE_URL).rstrip("/")
        self._timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else cfg.WILDAPRICOT_HTTP_TIMEOUT_SECONDS
        )
        rpm = (
            max_requests_per_minute
            if max_requests_per_minute is not None
            else cfg.WILDAPRICOT_MAX_REQUESTS_PER_MINUTE
        )
        self._throttle = RequestThrottle(max_requests_per_minute=rpm)
        self._retry_max_attempts = (
            retry_max_attempts
            if retry_max_attempts is not None
            else cfg.WILDAPRICOT_RETRY_MAX_ATTEMPTS
        )
        self._retry_429_delay = (
            retry_429_delay_seconds
            if retry_429_delay_seconds is not None
            else cfg.WILDAPRICOT_RETRY_429_DELAY_SECONDS
        )
        self._retry_429_max_delay = cfg.WILDAPRICOT_RETRY_429_MAX_DELAY_SECONDS
        configured = account_id if account_id is not None else cfg.WILDAPRICOT_ACCOUNT_ID
        self._account_id = self._token_manager.resolve_account_id(configured)
        logger.info(
            "WildApricot client initialized account_id=%s max_rpm=%s",
            self._account_id,
            rpm,
        )

    @property
    def account_id(self) -> int:
        return self._account_id

    def _account_base_path(self) -> str:
        return f"/v2/accounts/{self._account_id}"

    def _build_url(self, resource_path: str) -> str:
        path = resource_path if resource_path.startswith("/") else f"/{resource_path}"
        if path.startswith("/v2/"):
            return f"{self._api_base}{path}"
        return f"{self._api_base}{self._account_base_path()}{path}"

    def _authorization_header(self) -> dict[str, str]:
        token = self._token_manager.get_valid_token()
        return {"Authorization": f"{token.token_type} {token.access_token}"}

    def _execute_http(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None,
        json_body: Any,
        headers: dict[str, str],
    ) -> httpx.Response:
        try:
            # WARNING: SSL verification disabled for development
            # For production: install proper certificates or use certifi
            with httpx.Client(timeout=self._timeout, verify=False) as http:
                return http.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            logger.error("WildApricot HTTP error method=%s url=%s err=%s", method, url, exc)
            raise WildApricotAPIError(f"HTTP request failed: {exc}", endpoint=url) from exc

    def request(
        self,
        method: str,
        resource_path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        _retry_on_401: bool = True,
    ) -> Any:
        url = self._build_url(resource_path)
        headers_base = {"Accept": "application/json"}
        if json_body is not None:
            headers_base["Content-Type"] = "application/json"

        retried_401 = False
        last_429_response: httpx.Response | None = None

        for attempt in range(self._retry_max_attempts):
            self._throttle.wait()
            headers = {**headers_base, **self._authorization_header()}
            response = self._execute_http(
                method,
                url,
                params=params,
                json_body=json_body,
                headers=headers,
            )

            if response.status_code == 401 and _retry_on_401 and not retried_401:
                logger.info(
                    "WildApricot API 401; regenerating bearer token and retrying url=%s",
                    url,
                )
                self.regenerate_bearer_token()
                retried_401 = True
                continue

            if response.status_code == 429:
                last_429_response = response
                if attempt + 1 >= self._retry_max_attempts:
                    break
                delay = retry_delay_for_429(
                    response,
                    attempt=attempt,
                    base_delay_seconds=self._retry_429_delay,
                    max_delay_seconds=self._retry_429_max_delay,
                )
                logger.warning(
                    "WildApricot rate limited (429); sleeping %.1fs then retrying "
                    "(attempt %s/%s) url=%s",
                    delay,
                    attempt + 1,
                    self._retry_max_attempts,
                    url,
                )
                time.sleep(delay)
                continue

            return parse_json_response(response, url)

        if last_429_response is not None:
            body = (last_429_response.text or "")[:500]
            raise WildApricotAPIError(
                "API rate limit exceeded (429) after retries",
                status_code=429,
                endpoint=url,
                response_body=body,
            )

        raise WildApricotAPIError(
            f"API request failed after {self._retry_max_attempts} attempts",
            endpoint=url,
        )

    def get(self, resource_path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", resource_path, params=params)

    def regenerate_bearer_token(self) -> None:
        """Force a new OAuth access token (refresh grant, then client_credentials)."""
        try:
            self._token_manager.force_refresh()
        except WildApricotAuthError:
            self._token_manager.regenerate_token()

    def authenticate(self, *, _retried: bool = False) -> None:
        """Step 0: ensure a valid token is cached."""
        try:
            self._token_manager.get_valid_token()
        except WildApricotAuthError as exc:
            if exc.status_code == 401 and not _retried:
                logger.info("WildApricot authenticate 401; regenerating bearer token")
                self._token_manager.regenerate_token()
                self.authenticate(_retried=True)
                return
            raise
