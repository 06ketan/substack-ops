"""Auth bridge: read Substack creds from ~/.cursor/mcp.json (or env),
synthesize the cookies.json file that upstream `SubstackAuth` expects,
and return an authed session.

Cookie shape upstream wants (see substack_api/auth.py):
    [{"name", "value", "domain", "path", "secure"}, ...]
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
from dotenv import load_dotenv

from substack_ops._substack import SubstackAuth

DEFAULT_MCP_PATH = Path.home() / ".cursor" / "mcp.json"
DEFAULT_COOKIES_PATH = Path(".cache") / "cookies.json"


@dataclass(frozen=True)
class SubstackConfig:
    publication_url: str
    user_id: str
    session_token: str

    @property
    def session_token_decoded(self) -> str:
        # SUBSTACK_SESSION_TOKEN in mcp.json is URL-encoded ("s%3A...").
        # Substack's cookie value is the decoded form ("s:...").
        return unquote(self.session_token)


class AuthError(RuntimeError):
    pass


def _strip_jsonc(text: str) -> str:
    # mcp.json may contain // comments; strip them so json.loads works.
    return re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)


def _read_mcp_env(mcp_path: Path) -> dict[str, str]:
    if not mcp_path.exists():
        return {}
    try:
        raw = _strip_jsonc(mcp_path.read_text())
        data = json.loads(raw)
    except Exception as exc:
        raise AuthError(f"could not parse {mcp_path}: {exc}") from exc

    server = data.get("mcpServers", {}).get("substack-api", {})
    return server.get("env", {}) or {}


def load_config(mcp_path: Path | None = None) -> SubstackConfig:
    """Load Substack config from env first, then mcp.json fallback.

    Lookup order per field:
      1. process env (.env loaded automatically)
      2. mcp.json -> mcpServers.substack-api.env
    """
    load_dotenv()

    mcp_path = mcp_path or Path(os.environ.get("SUBSTACK_OPS_MCP_PATH", str(DEFAULT_MCP_PATH)))
    mcp_env = _read_mcp_env(mcp_path)

    def pick(key: str) -> str | None:
        return os.environ.get(key) or mcp_env.get(key)

    pub = pick("SUBSTACK_PUBLICATION_URL")
    uid = pick("SUBSTACK_USER_ID")
    tok = pick("SUBSTACK_SESSION_TOKEN")

    missing = [k for k, v in {
        "SUBSTACK_PUBLICATION_URL": pub,
        "SUBSTACK_USER_ID": uid,
        "SUBSTACK_SESSION_TOKEN": tok,
    }.items() if not v]

    if missing:
        raise AuthError(
            f"Missing Substack credentials: {', '.join(missing)}. "
            f"Checked env and {mcp_path}."
        )

    # Normalize publication URL: drop trailing slash for cleaner endpoint joining.
    pub = pub.rstrip("/")
    return SubstackConfig(publication_url=pub, user_id=str(uid), session_token=tok)


def write_cookies(cfg: SubstackConfig, cookies_path: Path | None = None) -> Path:
    """Build a cookies.json the upstream SubstackAuth can read."""
    cookies_path = cookies_path or DEFAULT_COOKIES_PATH
    cookies_path.parent.mkdir(parents=True, exist_ok=True)

    cookies: list[dict[str, Any]] = [
        {
            "name": "substack.sid",
            "value": cfg.session_token_decoded,
            "domain": ".substack.com",
            "path": "/",
            "secure": True,
        },
        {
            "name": "substack.lli",
            "value": "1",
            "domain": ".substack.com",
            "path": "/",
            "secure": True,
        },
    ]
    cookies_path.write_text(json.dumps(cookies, indent=2))
    # Restrict perms — file holds a session token.
    try:
        os.chmod(cookies_path, 0o600)
    except OSError:
        pass
    return cookies_path


def get_authed_session(
    mcp_path: Path | None = None,
    cookies_path: Path | None = None,
) -> tuple[SubstackAuth, SubstackConfig]:
    cfg = load_config(mcp_path)
    path = write_cookies(cfg, cookies_path)
    auth = SubstackAuth(cookies_path=str(path))
    if not auth.authenticated:
        raise AuthError("SubstackAuth refused to load cookies; check token.")
    return auth, cfg


def verify(
    mcp_path: Path | None = None,
    cookies_path: Path | None = None,
) -> dict[str, Any]:
    """Hit a known authed endpoint and confirm we are who we think we are.

    Substack's `/api/v1/subscriptions` returns the current user's subs list when
    authed; 401 / empty when not.
    """
    auth, cfg = get_authed_session(mcp_path, cookies_path)

    # Use a fresh httpx call with the same cookies to avoid upstream's 2s sleep.
    cookies = {
        "substack.sid": cfg.session_token_decoded,
        "substack.lli": "1",
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        r = client.get(
            "https://substack.com/api/v1/subscriptions",
            cookies=cookies,
            headers=headers,
        )
        sub_status = r.status_code
        data = r.json() if r.status_code == 200 else {}
        sub_count = len(data.get("subscriptions", [])) if data else None

        pub_users = data.get("publicationUsers") or []
        publications = data.get("publications") or []
        me = pub_users[0] if pub_users else {}

        # name resolution chain:
        # 1. publicationUsers[0].name
        # 2. matching publications[].name (publication title)
        # 3. publication subdomain
        # 4. handle parsed from publication_url
        name = me.get("name") or me.get("twitter_screen_name")
        my_pub_id = me.get("publication_id")
        publication_name = None
        if my_pub_id:
            for p in publications:
                if p.get("id") == my_pub_id:
                    publication_name = p.get("name")
                    break
        if not name:
            name = publication_name
        if not name:
            # parse subdomain from cfg.publication_url, e.g. ketanchavan.substack.com
            from urllib.parse import urlparse
            host = urlparse(cfg.publication_url).netloc
            name = host.split(".")[0] if host else None

    # auth is OK if subscriptions endpoint returned 200 AND we found our own
    # publicationUsers row (proves cookie maps to a real account).
    ok = sub_status == 200 and bool(pub_users)
    return {
        "ok": ok,
        "name": name,
        "publication_name": publication_name,
        "publication_id": my_pub_id,
        "user_id": cfg.user_id,
        "publication_url": cfg.publication_url,
        "subscriptions_count": sub_count,
        "subscriptions_status": sub_status,
        "auth": auth,
    }
