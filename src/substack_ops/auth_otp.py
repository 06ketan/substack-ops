"""Email magic-link login flow.

Substack sends a `magic` link to your email; clicking it returns a `Set-Cookie`
for `substack.sid`. We can't intercept that link automatically without a local
HTTP server, so the flow here is paste-the-link:

1. POST /api/v1/email-login {"email": ...}  → triggers email
2. User pastes the magic-link URL.
3. We GET the link with `follow_redirects=False`, capture `substack.sid` from
   the response cookies, write to .cache/cookies.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from substack_ops._substack._http import DEFAULT_HEADERS

REQUEST_URL = "https://substack.com/api/v1/email-login"
DEFAULT_COOKIES_PATH = Path(".cache") / "cookies.json"


def request_magic_link(email: str) -> dict[str, Any]:
    """Ask Substack to email a magic-link to `email`."""
    with httpx.Client(headers=DEFAULT_HEADERS, timeout=30) as client:
        r = client.post(REQUEST_URL, json={"email": email})
    return {"status": r.status_code, "body": r.text[:400]}


def consume_magic_link(
    link_url: str,
    cookies_path: Path | None = None,
) -> Path:
    """Visit the magic-link URL, capture the substack.sid cookie, save it."""
    cookies_path = cookies_path or DEFAULT_COOKIES_PATH
    cookies_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=30) as client:
        r = client.get(link_url)
    sid = r.cookies.get("substack.sid")
    if not sid:
        raise RuntimeError(
            "magic-link did not set substack.sid (link expired or wrong account?)"
        )
    out = [
        {"name": "substack.sid", "value": sid, "domain": ".substack.com", "path": "/", "secure": True},
        {"name": "substack.lli", "value": "1", "domain": ".substack.com", "path": "/", "secure": True},
    ]
    cookies_path.write_text(json.dumps(out, indent=2))
    try:
        os.chmod(cookies_path, 0o600)
    except OSError:
        pass
    return cookies_path
