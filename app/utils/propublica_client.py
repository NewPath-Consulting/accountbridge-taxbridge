"""ProPublica Nonprofit Explorer API v2 client.

Endpoints (https://projects.propublica.org/nonprofits/api):

    GET /search.json?q=...&page=N&state[id]=XX&ntee[id]=N&c_code[id]=N
        25 organizations per page. Organization objects only, no financials.
    GET /organizations/{ein}.json
        organization (IRS Business Master File profile), filings_with_data
        (one object per return with extracted line items), filings_without_data
        (form type and PDF link only).

The API is unauthenticated. Every response is cached on disk by URL so a
re-run costs nothing and repeated development does not hit ProPublica again.
Live requests are paced by ``delay_seconds``.

Network access is injectable (``fetch``) so the client is testable offline.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable, Dict, Iterator, Optional
from urllib.parse import urlencode

BASE_URL = "https://projects.propublica.org/nonprofits/api/v2"
DEFAULT_USER_AGENT = "TaxBridge routing harness (capstone research; contact via NewPath Consulting)"
FORMTYPE_990 = 0
FORMTYPE_990EZ = 1
FORMTYPE_990PF = 2


def _default_fetch(user_agent: str, timeout: float) -> Callable[[str], str]:
    def fetch(url: str) -> str:
        import httpx  # already a project dependency; imported lazily so the module loads offline

        response = httpx.get(url, headers={"User-Agent": user_agent}, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        return response.text

    return fetch


class ProPublicaClient:
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        delay_seconds: float = 0.5,
        fetch: Optional[Callable[[str], str]] = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 30.0,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay_seconds = delay_seconds
        self._fetch = fetch or _default_fetch(user_agent, timeout)
        self._last_request_at = 0.0
        self.live_requests = 0
        self.cache_hits = 0

    # ---- URL construction -------------------------------------------------

    @staticmethod
    def search_url(
        q: Optional[str] = None,
        page: int = 0,
        state: Optional[str] = None,
        ntee: Optional[int] = None,
        c_code: Optional[int] = None,
    ) -> str:
        params = []
        if q:
            params.append(("q", q))
        params.append(("page", str(page)))
        if state:
            params.append(("state[id]", state))
        if ntee is not None:
            params.append(("ntee[id]", str(ntee)))
        if c_code is not None:
            params.append(("c_code[id]", str(c_code)))
        return f"{BASE_URL}/search.json?{urlencode(params)}"

    @staticmethod
    def organization_url(ein: int | str) -> str:
        digits = "".join(ch for ch in str(ein) if ch.isdigit())
        return f"{BASE_URL}/organizations/{int(digits)}.json"

    # ---- Caching and pacing ---------------------------------------------------

    def _cache_path(self, url: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        return self.cache_dir / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json")

    def get_json(self, url: str) -> Dict:
        path = self._cache_path(url)
        if path and path.exists():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))

        wait = self.delay_seconds - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        text = self._fetch(url)
        self._last_request_at = time.monotonic()
        self.live_requests += 1

        data = json.loads(text)
        if path:
            path.write_text(json.dumps(data), encoding="utf-8")
        return data

    # ---- Endpoints ---------------------------------------------------------------

    def search(
        self,
        q: Optional[str] = None,
        page: int = 0,
        state: Optional[str] = None,
        ntee: Optional[int] = None,
        c_code: Optional[int] = None,
    ) -> Dict:
        return self.get_json(self.search_url(q=q, page=page, state=state, ntee=ntee, c_code=c_code))

    def iter_search(
        self,
        q: Optional[str] = None,
        state: Optional[str] = None,
        ntee: Optional[int] = None,
        c_code: Optional[int] = None,
        max_pages: Optional[int] = None,
    ) -> Iterator[Dict]:
        """Yield organization objects across result pages."""
        page = 0
        while True:
            data = self.search(q=q, page=page, state=state, ntee=ntee, c_code=c_code)
            organizations = data.get("organizations") or []
            for org in organizations:
                yield org
            num_pages = int(data.get("num_pages") or 0)
            page += 1
            if page >= num_pages or not organizations:
                return
            if max_pages is not None and page >= max_pages:
                return

    def organization(self, ein: int | str) -> Dict:
        return self.get_json(self.organization_url(ein))
