"""Cookie-loading SubstackAuth — httpx port of upstream NHagar/substack_api.

Loads JSON cookies from disk (shape: list of {name, value, domain, path, secure})
and exposes `.get/.post` for authed requests. The upstream uses requests; we use
httpx so the rest of the codebase has a single HTTP stack.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from substack_ops._substack._http import DEFAULT_HEADERS


class SubstackAuth:
    def __init__(self, cookies_path: str) -> None:
        self.cookies_path = cookies_path
        self.session = httpx.Client(
            headers={**DEFAULT_HEADERS, "Content-Type": "application/json"},
            follow_redirects=True,
            timeout=30,
        )
        self.authenticated = False
        if os.path.exists(self.cookies_path):
            self.load_cookies()
            self.authenticated = True
        else:
            self.session.cookies.clear()

    def load_cookies(self) -> bool:
        try:
            with open(self.cookies_path, "r") as f:
                cookies = json.load(f)
            for cookie in cookies:
                self.session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie.get("domain"),
                    path=cookie.get("path", "/"),
                )
            return True
        except Exception:
            return False

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.session.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.session.post(url, **kwargs)

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass
