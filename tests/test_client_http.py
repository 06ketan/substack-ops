"""Mocked HTTP for client.get_comments + post_comment_reply."""

from __future__ import annotations

import json
from typing import Any

import httpx

from substack_ops._substack import SubstackAuth
from substack_ops.auth import SubstackConfig, write_cookies
from substack_ops.client import SubstackClient


def _build_client(tmp_path, handler) -> SubstackClient:
    cfg = SubstackConfig(
        publication_url="https://test.substack.com",
        user_id="42",
        session_token="s%3Atok",
    )
    cookies_path = write_cookies(cfg, tmp_path / "cookies.json")
    auth = SubstackAuth(cookies_path=str(cookies_path))
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, timeout=5)
    return SubstackClient(cfg=cfg, auth=auth, http=http)


def test_get_comments_returns_tree(tmp_path):
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        return httpx.Response(
            200, json={"comments": [{"id": 1, "body": "hi", "children": []}]}
        )

    with _build_client(tmp_path, handler) as c:
        data = c.get_comments(123)

    assert data["comments"][0]["id"] == 1
    assert "/api/v1/post/123/comments" in seen["url"]
    assert "all_comments=true" in seen["url"]


def test_post_comment_reply_dry_run_does_not_call(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"dry_run should not hit network, got {req.url}")

    with _build_client(tmp_path, handler) as c:
        out = c.post_comment_reply(post_id=10, body="hello", parent_id=5, dry_run=True)
    assert out["_dry_run"] is True
    assert out["payload"] == {"body": "hello", "parent_id": 5}


def test_post_comment_reply_live_posts(tmp_path):
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": 7777, "body": "hello"})

    with _build_client(tmp_path, handler) as c:
        out = c.post_comment_reply(
            post_id=10, body="hello", parent_id=5, dry_run=False
        )

    assert out["id"] == 7777
    assert captured["url"].endswith("/api/v1/post/10/comment")
    assert captured["body"] == {"body": "hello", "parent_id": 5}
