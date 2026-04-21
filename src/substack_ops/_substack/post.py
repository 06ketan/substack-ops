"""Post wrapper — httpx port of NHagar/substack_api/post.py."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from substack_ops._substack._http import shared_client
from substack_ops._substack.auth import SubstackAuth


class Post:
    def __init__(self, url: str, auth: SubstackAuth | None = None) -> None:
        self.url = url
        self.auth = auth
        parsed = urlparse(url)
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        path_parts = parsed.path.strip("/").split("/")
        self.slug = path_parts[-1] if path_parts else None
        self.endpoint = f"{self.base_url}/api/v1/posts/{self.slug}"
        self._post_data: dict[str, Any] | None = None

    def __repr__(self) -> str:
        return f"Post(url={self.url!r})"

    def _fetch(self, force_refresh: bool = False) -> dict[str, Any]:
        if self._post_data is not None and not force_refresh:
            return self._post_data
        if self.auth and self.auth.authenticated:
            r = self.auth.get(self.endpoint, timeout=30)
        else:
            with shared_client() as c:
                r = c.get(self.endpoint, timeout=30)
        r.raise_for_status()
        self._post_data = r.json()
        return self._post_data

    def get_metadata(self, force_refresh: bool = False) -> dict[str, Any]:
        return self._fetch(force_refresh=force_refresh)

    def get_content(self, force_refresh: bool = False) -> str | None:
        data = self._fetch(force_refresh=force_refresh)
        return data.get("body_html")

    def is_paywalled(self) -> bool:
        return self._fetch().get("audience") == "only_paid"
