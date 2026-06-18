"""Rate limiting and 429 retry helpers for WildApricot API (30 req/min limit)."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


class RequestThrottle:
    """Enforce minimum spacing between API calls to stay under per-minute limits."""

    def __init__(self, *, max_requests_per_minute: int) -> None:
        rpm = max(1, max_requests_per_minute)
        self._min_interval = 60.0 / rpm
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            if elapsed < self._min_interval:
                sleep_for = self._min_interval - elapsed
                logger.debug("WildApricot throttle sleeping %.2fs", sleep_for)
                time.sleep(sleep_for)
            self._last_request_at = time.monotonic()


def parse_retry_after(response: httpx.Response, *, default_seconds: float) -> float:
    """Parse Retry-After header (seconds or HTTP-date); fall back to default."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return default_seconds
    raw = raw.strip()
    try:
        return max(float(int(raw)), 1.0)
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(raw)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        delay = retry_at.timestamp() - datetime.now(timezone.utc).timestamp()
        return max(delay, 1.0)
    except (TypeError, ValueError, OverflowError):
        return default_seconds


def retry_delay_for_429(
    response: httpx.Response,
    *,
    attempt: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
) -> float:
    """Compute sleep duration before retrying after HTTP 429."""
    header_delay = parse_retry_after(response, default_seconds=base_delay_seconds)
    exponential = base_delay_seconds * (2**attempt)
    return min(max(header_delay, exponential), max_delay_seconds)
