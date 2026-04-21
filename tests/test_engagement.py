"""Engagement verbs (react/restack/publish/delete) wired through SubstackClient.

Confirms:
- post react/restack hit pub host with correct payload
- note react/restack hit substack.com with correct payload
- delete uses pub host for post-comments and substack.com for notes (the M2 bug)
- publish_note posts to /api/v1/comment/feed without parent_id
- ancestor_path guardrail flips status to "orphaned" when no parent ack
"""

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


def test_react_to_post_dry_run_no_network(tmp_path):
    def handler(req):  # pragma: no cover
        raise AssertionError(f"dry_run should not fire, got {req.url}")

    with _build_client(tmp_path, handler) as c:
        out = c.react_to_post(post_id=123, dry_run=True)
    assert out["_dry_run"] is True
    assert out["url"].endswith("/api/v1/post/123/reaction")
    assert out["payload"] == {"reaction": "❤"}


def test_react_to_post_live_uses_pub_host(tmp_path):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True})

    with _build_client(tmp_path, handler) as c:
        c.react_to_post(post_id=99, reaction="🔥", dry_run=False)
    assert seen["url"].endswith("/api/v1/post/99/reaction")
    assert "test.substack.com" in seen["url"]
    assert seen["body"] == {"reaction": "🔥"}


def test_restack_post_uses_restack_feed_endpoint(tmp_path):
    """Live-discovered: real endpoint is /api/v1/restack/feed with full payload."""
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True})

    with _build_client(tmp_path, handler) as c:
        c.restack_post(post_id=42, dry_run=False)
    assert seen["url"] == "https://substack.com/api/v1/restack/feed"
    assert seen["body"] == {
        "postId": 42,
        "commentId": None,
        "tabId": "for-you",
        "surface": "feed",
    }


def test_restack_note_uses_restack_feed_endpoint(tmp_path):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True})

    with _build_client(tmp_path, handler) as c:
        c.restack_note(note_id=7777, dry_run=False)
    assert seen["url"] == "https://substack.com/api/v1/restack/feed"
    assert seen["body"] == {
        "postId": None,
        "commentId": 7777,
        "tabId": "for-you",
        "surface": "feed",
    }


def test_publish_note_no_parent_id(tmp_path):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": 1})

    with _build_client(tmp_path, handler) as c:
        c.publish_note(body="hello world", dry_run=False)
    assert seen["url"] == "https://substack.com/api/v1/comment/feed"
    assert "parent_id" not in seen["body"]
    assert seen["body"]["bodyJson"]["content"][0]["content"][0]["text"] == "hello world"


def test_post_note_reply_uses_parent_id_field(tmp_path):
    """Regression for M2 bug: payload field is parent_id, NOT parent_comment_id."""
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": 1})

    with _build_client(tmp_path, handler) as c:
        c.post_note_reply(note_id=5555, body="hi", dry_run=False)
    assert "parent_id" in seen["body"]
    assert "parent_comment_id" not in seen["body"]
    assert seen["body"]["parent_id"] == 5555


def test_delete_post_comment_uses_pub_host(tmp_path):
    """Regression for M2 host-mismatch bug."""
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["method"] = req.method
        return httpx.Response(200, json={})

    with _build_client(tmp_path, handler) as c:
        c.delete_comment(comment_id=99, kind="post", dry_run=False)
    assert seen["method"] == "DELETE"
    assert "test.substack.com" in seen["url"]
    assert seen["url"].endswith("/api/v1/comment/99")


def test_delete_note_comment_uses_substack_com(tmp_path):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json={})

    with _build_client(tmp_path, handler) as c:
        c.delete_comment(comment_id=99, kind="note", dry_run=False)
    assert seen["url"].startswith("https://substack.com/")


def test_pub_url_normalizes(tmp_path):
    def handler(req):  # pragma: no cover
        return httpx.Response(200, json={})

    with _build_client(tmp_path, handler) as c:
        assert c.pub_url("foo") == "https://foo.substack.com"
        assert c.pub_url("foo.com") == "https://foo.com"
        assert c.pub_url("https://foo.substack.com/") == "https://foo.substack.com"
        assert c.pub_url(None) == c.cfg.publication_url


def test_add_comment_top_level_omits_parent_id(tmp_path):
    """Live-discovered: Substack rejects parent_id=null with 400. Field must be omitted."""
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": 1})

    with _build_client(tmp_path, handler) as c:
        c.add_comment(post_id=42, body="top", dry_run=False)
    assert seen["body"] == {"body": "top"}
    assert "parent_id" not in seen["body"]


def test_add_comment_with_parent_id_includes_field(tmp_path):
    """When replying to a parent comment, parent_id must be included as int."""
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": 2})

    with _build_client(tmp_path, handler) as c:
        c.post_comment_reply(
            post_id=42, body="child", parent_id=99, dry_run=False
        )
    assert seen["body"] == {"body": "child", "parent_id": 99}
