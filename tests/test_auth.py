"""auth.py: config loading + cookie shape."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from substack_ops.auth import (
    AuthError,
    SubstackConfig,
    _read_mcp_env,
    _strip_jsonc,
    load_config,
    write_cookies,
)


def test_strip_jsonc_removes_line_comments():
    src = """
{
    // top
    "a": 1, // inline kept (json doesn't allow this)
    "b": 2
}
"""
    out = _strip_jsonc(src)
    assert "// top" not in out
    # Only line-leading comments are stripped, by design.
    assert "// inline" in out


def test_read_mcp_env(tmp_path: Path):
    p = tmp_path / "mcp.json"
    p.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "substack-api": {
                        "env": {"SUBSTACK_USER_ID": "42", "SUBSTACK_SESSION_TOKEN": "tok"}
                    }
                }
            }
        )
    )
    env = _read_mcp_env(p)
    assert env["SUBSTACK_USER_ID"] == "42"


def test_load_config_env_takes_precedence(tmp_path: Path, monkeypatch):
    p = tmp_path / "mcp.json"
    p.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "substack-api": {
                        "env": {
                            "SUBSTACK_PUBLICATION_URL": "https://from-mcp.substack.com/",
                            "SUBSTACK_USER_ID": "1",
                            "SUBSTACK_SESSION_TOKEN": "frommcp",
                        }
                    }
                }
            }
        )
    )
    monkeypatch.setenv("SUBSTACK_PUBLICATION_URL", "https://env.substack.com/")
    monkeypatch.setenv("SUBSTACK_USER_ID", "999")
    monkeypatch.setenv("SUBSTACK_SESSION_TOKEN", "envtok")
    cfg = load_config(p)
    assert cfg.publication_url == "https://env.substack.com"
    assert cfg.user_id == "999"
    assert cfg.session_token == "envtok"


def test_load_config_missing_raises(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SUBSTACK_PUBLICATION_URL", raising=False)
    monkeypatch.delenv("SUBSTACK_USER_ID", raising=False)
    monkeypatch.delenv("SUBSTACK_SESSION_TOKEN", raising=False)
    with pytest.raises(AuthError):
        load_config(tmp_path / "missing.json")


def test_write_cookies_url_decodes_token(tmp_path: Path):
    cfg = SubstackConfig(
        publication_url="https://x.substack.com",
        user_id="1",
        session_token="s%3Aabc.def",  # URL-encoded
    )
    out = write_cookies(cfg, tmp_path / "cookies.json")
    data = json.loads(out.read_text())
    sid = next(c for c in data if c["name"] == "substack.sid")
    assert sid["value"] == "s:abc.def"  # decoded
    assert any(c["name"] == "substack.lli" for c in data)
