"""Newsletter wrapper — httpx port of NHagar/substack_api/newsletter.py."""

from __future__ import annotations

import re
import time
import urllib.parse
from typing import Any

import httpx

from substack_ops._substack._http import DEFAULT_HEADERS, DISCOVERY_HEADERS, shared_client
from substack_ops._substack.auth import SubstackAuth

SEARCH_URL = "https://substack.com/api/v1/publication/search"


def _host_from_url(url: str) -> str:
    return urllib.parse.urlparse(
        url if "://" in url else f"https://{url}"
    ).netloc.lower()


def _match_publication(search_results: dict, host: str) -> dict | None:
    for item in search_results.get("publications", []):
        if (item.get("custom_domain") and _host_from_url(item["custom_domain"]) == host) or (
            item.get("subdomain")
            and f"{item['subdomain'].lower()}.substack.com" == host
        ):
            return item
    m = re.match(r"^([a-z0-9-]+)\.substack\.com$", host)
    if m:
        sub = m.group(1)
        for item in search_results.get("publications", []):
            if item.get("subdomain", "").lower() == sub:
                return item
    return None


class Newsletter:
    def __init__(self, url: str, auth: SubstackAuth | None = None) -> None:
        self.url = url.rstrip("/")
        self.auth = auth

    def __repr__(self) -> str:
        return f"Newsletter(url={self.url!r})"

    def _make_request(self, endpoint: str, **kwargs: Any) -> httpx.Response:
        if self.auth and self.auth.authenticated:
            resp = self.auth.get(endpoint, **kwargs)
        else:
            with shared_client() as client:
                resp = client.get(endpoint, **kwargs)
        time.sleep(0.5)
        return resp

    def _fetch_paginated_posts(
        self,
        params: dict[str, str],
        limit: int | None = None,
        page_size: int = 15,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        offset = 0
        more = True
        while more:
            current = {**params, "offset": str(offset), "limit": str(page_size)}
            qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in current.items())
            endpoint = f"{self.url}/api/v1/archive?{qs}"
            r = self._make_request(endpoint, timeout=30)
            r.raise_for_status()
            items = r.json()
            if not items:
                break
            results.extend(items)
            offset += page_size
            if limit and len(results) >= limit:
                results = results[:limit]
                more = False
            if len(items) < page_size:
                more = False
        return results

    def get_posts(
        self, sorting: str = "new", limit: int | None = None
    ) -> list[dict[str, Any]]:
        return self._fetch_paginated_posts({"sort": sorting}, limit)

    def search_posts(self, query: str, limit: int | None = None) -> list[dict[str, Any]]:
        return self._fetch_paginated_posts({"sort": "new", "search": query}, limit)

    def get_podcasts(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self._fetch_paginated_posts({"sort": "new", "type": "podcast"}, limit)

    def _resolve_publication_id(self) -> int | None:
        host = _host_from_url(self.url)
        params = {
            "query": host.split(":")[0],
            "page": 0,
            "limit": 25,
            "skipExplanation": "true",
            "sort": "relevance",
        }
        with httpx.Client(headers=DISCOVERY_HEADERS, timeout=30) as client:
            r = client.get(SEARCH_URL, params=params)
            r.raise_for_status()
            match = _match_publication(r.json(), host)
            return match.get("id") if match else None

    def get_recommendations(self) -> list["Newsletter"]:
        publication_id = self._resolve_publication_id()
        if not publication_id:
            try:
                posts = self.get_posts(limit=1)
                publication_id = posts[0].get("publication_id") if posts else None
            except Exception:
                publication_id = None
        if not publication_id:
            return []
        endpoint = f"{self.url}/api/v1/recommendations/from/{publication_id}"
        r = self._make_request(endpoint, timeout=30)
        r.raise_for_status()
        recs = r.json() or []
        urls: list[str] = []
        for rec in recs:
            pub = rec.get("recommendedPublication", {})
            if pub.get("custom_domain"):
                urls.append(pub["custom_domain"])
            elif pub.get("subdomain"):
                urls.append(f"https://{pub['subdomain']}.substack.com")
        return [Newsletter(u, auth=self.auth) for u in urls]

    def get_authors(self) -> list[dict[str, Any]]:
        endpoint = f"{self.url}/api/v1/publication/users/ranked?public=true"
        r = self._make_request(endpoint, timeout=30)
        r.raise_for_status()
        return r.json() or []

    @property
    def headers(self) -> dict[str, str]:
        return DEFAULT_HEADERS
