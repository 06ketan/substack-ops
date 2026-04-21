"""Shared httpx defaults for vendored upstream wrappers."""

from __future__ import annotations

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}

DISCOVERY_HEADERS = {
    **DEFAULT_HEADERS,
    "Origin": "https://substack.com",
    "Referer": "https://substack.com/discover",
}


def shared_client(*, follow_redirects: bool = True, timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=follow_redirects,
        headers=DEFAULT_HEADERS,
    )
