"""WildApricot Admin API v2 — supporting-source resources for Form 990."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.adapters.wildapricot.http import ensure_list
from app.adapters.wildapricot.pagination import DEFAULT_PAGE_SIZE, fetch_all_pages

if TYPE_CHECKING:
    from app.adapters.wildapricot.client import WildApricotClient

logger = logging.getLogger(__name__)

# Priority order for extraction (invoices → payments → contacts → events → registrations → donations)
SUPPORTED_RESOURCES = (
    "invoices",
    "payments",
    "contacts",
    "events",
    "event_registrations",
    "donations",
)


class WildApricotResources:
    """WildApricot APIs used as supporting source for membership, program, and revenue data."""

    def __init__(self, client: WildApricotClient) -> None:
        self._client = client

    def _list_paginated(
        self,
        resource_path: str,
        *,
        extra_params: dict[str, Any] | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        base_params = dict(extra_params or {})

        def fetch_page(skip: int, top: int) -> list[dict[str, Any]]:
            params = {**base_params, "$skip": skip, "$top": top}
            data = self._client.get(resource_path, params=params)
            return ensure_list(data, resource_path)

        return fetch_all_pages(fetch_page, page_size=page_size)

    def list_invoices(
        self,
        *,
        contact_id: int | str | None = None,
        event_id: int | str | None = None,
    ) -> list[dict[str, Any]]:
        """Revenue validation."""
        params: dict[str, Any] = {}
        if contact_id is not None:
            params["contactId"] = contact_id
        if event_id is not None:
            params["eventId"] = event_id
        return self._list_paginated("/invoices", extra_params=params or None)

    def list_payments(self, contact_id: int | str | None = None) -> list[dict[str, Any]]:
        """Revenue validation."""
        params: dict[str, Any] = {}
        if contact_id is not None:
            params["contactId"] = contact_id
        return self._list_paginated("/payments", extra_params=params or None)

    def list_contacts(self, **filters: Any) -> list[dict[str, Any]]:
        """Membership statistics."""
        return self._list_paginated("/contacts", extra_params=filters or None)

    def list_events(self) -> list[dict[str, Any]]:
        """Program metrics and event participation."""
        return self._list_paginated("/events")

    def list_event_registrations(self, event_id: int | str) -> list[dict[str, Any]]:
        """Event participation."""
        return self._list_paginated(
            "/eventregistrations",
            extra_params={"eventId": event_id},
        )

    def list_donations(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Program metrics / donor activity."""
        params: dict[str, Any] = {}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        return self._list_paginated("/donations", extra_params=params or None)
