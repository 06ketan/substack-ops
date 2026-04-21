"""User wrapper + handle-redirect resolver."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from substack_ops._substack._http import shared_client


def resolve_handle_redirect(old_handle: str, timeout: int = 30) -> str | None:
    """Follow https://substack.com/@{old_handle} and return the new handle if renamed."""
    try:
        with shared_client(timeout=timeout) as client:
            response = client.get(f"https://substack.com/@{old_handle}")
        if response.status_code != 200:
            return None
        parsed = urlparse(str(response.url))
        path_parts = parsed.path.strip("/").split("/")
        if path_parts and path_parts[0].startswith("@"):
            new = path_parts[0][1:]
            if new and new != old_handle:
                return new
        return None
    except httpx.RequestError:
        return None


class User:
    def __init__(self, username: str, follow_redirects: bool = True) -> None:
        self.username = username
        self.original_username = username
        self.follow_redirects = follow_redirects
        self.endpoint = f"https://substack.com/api/v1/user/{username}/public_profile"
        self._user_data: dict[str, Any] | None = None
        self._redirect_attempted = False

    def __repr__(self) -> str:
        return f"User(username={self.username!r})"

    def _update_handle(self, new_handle: str) -> None:
        self.username = new_handle
        self.endpoint = f"https://substack.com/api/v1/user/{new_handle}/public_profile"

    def _fetch(self, force_refresh: bool = False) -> dict[str, Any]:
        if self._user_data is not None and not force_refresh:
            return self._user_data
        with shared_client() as client:
            r = client.get(self.endpoint)
            if r.status_code == 404 and self.follow_redirects and not self._redirect_attempted:
                self._redirect_attempted = True
                new = resolve_handle_redirect(self.username)
                if new:
                    self._update_handle(new)
                    r = client.get(self.endpoint)
            r.raise_for_status()
        self._user_data = r.json()
        return self._user_data

    def get_raw_data(self, force_refresh: bool = False) -> dict[str, Any]:
        return self._fetch(force_refresh=force_refresh)

    @property
    def id(self) -> int:
        return self._fetch()["id"]

    @property
    def name(self) -> str:
        return self._fetch()["name"]

    @property
    def was_redirected(self) -> bool:
        return self.username != self.original_username

    def get_subscriptions(self) -> list[dict[str, Any]]:
        data = self._fetch()
        out: list[dict[str, Any]] = []
        for sub in data.get("subscriptions", []):
            pub = sub["publication"]
            domain = pub.get("custom_domain") or f"{pub['subdomain']}.substack.com"
            out.append(
                {
                    "publication_id": pub["id"],
                    "publication_name": pub["name"],
                    "domain": domain,
                    "membership_state": sub["membership_state"],
                }
            )
        return out
