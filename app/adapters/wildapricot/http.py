"""HTTP helpers for WildApricot API responses."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.adapters.wildapricot.exceptions import WildApricotAPIError

logger = logging.getLogger(__name__)

MAX_ERROR_BODY_LEN = 500


def parse_json_response(response: httpx.Response, endpoint: str) -> Any:
    if response.status_code >= 400:
        body = (response.text or "")[:MAX_ERROR_BODY_LEN]
        logger.warning(
            "WildApricot API error status=%s endpoint=%s body=%s",
            response.status_code,
            endpoint,
            body,
        )
        raise WildApricotAPIError(
            f"API request failed with status {response.status_code}",
            status_code=response.status_code,
            endpoint=endpoint,
            response_body=body,
        )

    if response.status_code == 204 or not response.content:
        return None

    try:
        return response.json()
    except ValueError as exc:
        raise WildApricotAPIError(
            "API response was not valid JSON",
            status_code=response.status_code,
            endpoint=endpoint,
        ) from exc


_COLLECTION_KEYS = (
    "Events",
    "events",
    "Contacts",
    "contacts",
    "Donations",
    "donations",
    "Invoices",
    "invoices",
    "Payments",
    "payments",
    "Refunds",
    "refunds",
    "EventRegistrations",
    "eventRegistrations",
    "eventregistrations",
    "MembershipLevels",
    "membershiplevels",
    "PaymentAllocations",
    "paymentallocations",
)


def unwrap_collection(data: Any) -> Any:
    """Unwrap WildApricot list payloads such as {\"Events\": [...]}."""
    if isinstance(data, dict):
        for key in _COLLECTION_KEYS:
            value = data.get(key)
            if isinstance(value, list):
                return value
    return data


def ensure_list(data: Any, endpoint: str) -> list[dict[str, Any]]:
    if data is None:
        return []
    data = unwrap_collection(data)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    raise WildApricotAPIError(
        f"Expected list response from {endpoint}",
        endpoint=endpoint,
    )
