"""
QuickBooks API client for fetching financial reports.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any
import warnings

import httpx

# Suppress SSL verification warnings for development
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

from app.adapters.quickbooks.auth import TokenManager
from app.adapters.quickbooks.exceptions import QuickBooksAPIError, QuickBooksAuthError
from app.adapters.quickbooks.rate_limit import AsyncRequestThrottle, retry_delay_for_429
from app.config.settings import Settings, settings

logger = logging.getLogger(__name__)


class QuickBooksClient:
    """Client for interacting with QuickBooks Sandbox API."""

    def __init__(
        self,
        app_settings: Settings | None = None,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
        realm_id: str | None = None,
    ) -> None:
        """Initialize QuickBooks client from inline credentials or settings."""
        from app.adapters.quickbooks.auth import _sanitize_oauth_token

        cfg = app_settings or settings
        self.realm_id = realm_id or cfg.QUICKBOOKS_REALM_ID
        self.base_url = cfg.QUICKBOOKS_SANDBOX_BASE_URL.rstrip("/")
        self.output_dir = cfg.QUICKBOOKS_OUTPUT_DIR
        self._timeout = cfg.QUICKBOOKS_HTTP_TIMEOUT_SECONDS
        self._retry_max_attempts = cfg.QUICKBOOKS_RETRY_MAX_ATTEMPTS
        self._retry_429_delay = cfg.QUICKBOOKS_RETRY_429_DELAY_SECONDS
        self._retry_429_max_delay = cfg.QUICKBOOKS_RETRY_429_MAX_DELAY_SECONDS

        effective_client_id = _sanitize_oauth_token(client_id or cfg.QUICKBOOKS_CLIENT_ID)
        effective_client_secret = _sanitize_oauth_token(
            client_secret or cfg.QUICKBOOKS_CLIENT_SECRET
        )
        effective_refresh_token = _sanitize_oauth_token(
            refresh_token or cfg.QUICKBOOKS_REFRESH_TOKEN or ""
        ) or None
        effective_access_token = _sanitize_oauth_token(
            access_token or cfg.QUICKBOOKS_ACCESS_TOKEN or ""
        ) or None

        self._token_manager = TokenManager(
            client_id=effective_client_id,
            client_secret=effective_client_secret,
            oauth_url=cfg.QUICKBOOKS_OAUTH_URL,
            access_token=effective_access_token,
            refresh_token=effective_refresh_token,
            auth_code=None if (client_id or refresh_token or access_token) else (cfg.QUICKBOOKS_AUTH_CODE or None),
            redirect_uri=cfg.QUICKBOOKS_REDIRECT_URI or None,
            refresh_buffer_seconds=cfg.QUICKBOOKS_TOKEN_REFRESH_BUFFER_SECONDS,
            timeout_seconds=self._timeout,
        )
        self._throttle = AsyncRequestThrottle(
            max_requests_per_minute=cfg.QUICKBOOKS_MAX_REQUESTS_PER_MINUTE
        )

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        logger.info(
            "QuickBooks client initialized realm_id=%s max_rpm=%s",
            self.realm_id or "(none)",
            cfg.QUICKBOOKS_MAX_REQUESTS_PER_MINUTE,
        )

    def _authorization_header(self) -> dict[str, str]:
        token = self._token_manager.get_valid_token()
        return {"Authorization": f"{token.token_type} {token.access_token}"}

    def _get_headers(self) -> dict[str, str]:
        """Get authorization headers for API requests."""
        return {
            **self._authorization_header(),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get_report_params(self, start_date: str, end_date: str) -> dict[str, str]:
        """
        Get query parameters for report requests.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            Dictionary of query parameters
        """
        return {
            "start_date": start_date,
            "end_date": end_date,
            "accounting_method": "Accrual",
            "minorversion": "75",
        }

    async def _execute_http(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None,
        headers: dict[str, str],
    ) -> httpx.Response:
        try:
            # WARNING: SSL verification disabled for development
            # For production: install proper certificates or use certifi
            async with httpx.AsyncClient(timeout=self._timeout, verify=False) as http:
                return await http.request(method, url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            logger.error("QuickBooks HTTP error method=%s url=%s err=%s", method, url, exc)
            raise QuickBooksAPIError(f"HTTP request failed: {exc}", endpoint=url) from exc

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        _retry_on_401: bool = True,
    ) -> httpx.Response:
        retried_401 = False
        last_429_response: httpx.Response | None = None

        for attempt in range(self._retry_max_attempts):
            await self._throttle.wait()
            headers = self._get_headers()
            response = await self._execute_http(
                method,
                url,
                params=params,
                headers=headers,
            )

            if response.status_code == 401 and _retry_on_401 and not retried_401:
                logger.info(
                    "QuickBooks API 401; refreshing bearer token and retrying url=%s",
                    url,
                )
                try:
                    self._token_manager.force_refresh()
                except QuickBooksAuthError:
                    self._token_manager.invalidate()
                    self._token_manager.force_refresh()
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
                    "QuickBooks rate limited (429); sleeping %.1fs then retrying "
                    "(attempt %s/%s) url=%s",
                    delay,
                    attempt + 1,
                    self._retry_max_attempts,
                    url,
                )
                await asyncio.sleep(delay)
                continue

            if response.is_error:
                body = (response.text or "")[:500]
                raise QuickBooksAPIError(
                    f"QuickBooks API error: HTTP {response.status_code}",
                    status_code=response.status_code,
                    endpoint=url,
                    response_body=body,
                )

            return response

        if last_429_response is not None:
            body = (last_429_response.text or "")[:500]
            raise QuickBooksAPIError(
                "API rate limit exceeded (429) after retries",
                status_code=429,
                endpoint=url,
                response_body=body,
            )

        raise QuickBooksAPIError(
            f"API request failed after {self._retry_max_attempts} attempts",
            endpoint=url,
        )

    async def _fetch_report(
        self,
        realm_id: str,
        report_name: str,
        start_date: str,
        end_date: str,
        output_filename: str,
    ) -> dict[str, Any]:
        """
        Generic method to fetch a QuickBooks report.

        Args:
            realm_id: QuickBooks company/realm ID
            report_name: Name of the report (e.g., 'ProfitAndLoss', 'BalanceSheet')
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            output_filename: Name of the file to save the response

        Returns:
            Parsed JSON response from QuickBooks API
        """
        url = f"{self.base_url}/v3/company/{realm_id}/reports/{report_name}"
        params = self._get_report_params(start_date, end_date)

        logger.info(
            "Fetching %s report for realm %s from %s to %s",
            report_name,
            realm_id,
            start_date,
            end_date,
        )

        response = await self._request("GET", url, params=params)
        data = response.json()

        output_path = Path(self.output_dir) / output_filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(
            "Successfully fetched %s report. Saved to %s",
            report_name,
            output_path,
        )
        return data

    async def get_profit_and_loss(
        self,
        realm_id: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """
        Fetch Profit and Loss report from QuickBooks.

        Args:
            realm_id: QuickBooks company/realm ID
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            Parsed JSON response containing Profit and Loss data
        """
        return await self._fetch_report(
            realm_id=realm_id,
            report_name="ProfitAndLoss",
            start_date=start_date,
            end_date=end_date,
            output_filename="profit-and-loss.json",
        )

    async def get_balance_sheet(
        self,
        realm_id: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """
        Fetch Balance Sheet report from QuickBooks.

        Args:
            realm_id: QuickBooks company/realm ID
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            Parsed JSON response containing Balance Sheet data
        """
        return await self._fetch_report(
            realm_id=realm_id,
            report_name="BalanceSheet",
            start_date=start_date,
            end_date=end_date,
            output_filename="balance-sheet.json",
        )

    async def authenticate(self) -> None:
        """Ensure a valid access token is cached (refreshes if near expiry)."""
        self._token_manager.get_valid_token()
