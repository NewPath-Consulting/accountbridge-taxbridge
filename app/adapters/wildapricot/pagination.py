"""Paginate WildApricot list endpoints using $skip and $top."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 100


def fetch_all_pages(
    fetch_page: Callable[[int, int], list[dict[str, Any]]],
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> list[dict[str, Any]]:
    """
    Call fetch_page(skip, top) until a page returns fewer than page_size items.
    """
    all_items: list[dict[str, Any]] = []
    skip = 0

    while True:
        page = fetch_page(skip, page_size)
        if not page:
            break
        all_items.extend(page)
        logger.debug("WildApricot page fetched skip=%s count=%s", skip, len(page))
        if len(page) < page_size:
            break
        skip += page_size

    return all_items
