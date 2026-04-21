"""propose_reply -> confirm_reply token loop."""

from __future__ import annotations

import pytest

from substack_ops.mcp import server as mcp_server


@pytest.fixture(autouse=True)
def _clear_proposals():
    mcp_server._proposals.clear()
    yield
    mcp_server._proposals.clear()


def test_propose_reply_post_returns_token():
    out = mcp_server._dispatch(
        "propose_reply",
        {
            "kind": "post",
            "post_id": "12345",
            "parent_comment_id": "67890",
            "body": "thanks for the kind words",
        },
    )
    assert "token" in out and len(out["token"]) == 16
    assert out["preview"]["kind"] == "post"
    assert out["preview"]["body"] == "thanks for the kind words"
    assert out["expires_in"] == 300
    assert out["token"] in mcp_server._proposals


def test_propose_reply_post_requires_parent_comment_id():
    with pytest.raises(ValueError, match="parent_comment_id"):
        mcp_server._dispatch(
            "propose_reply",
            {"kind": "post", "post_id": "12345", "body": "hi"},
        )


def test_propose_reply_note_path():
    out = mcp_server._dispatch(
        "propose_reply",
        {"kind": "note", "note_id": "555", "body": "agreed"},
    )
    assert out["preview"]["kind"] == "note"
    assert out["preview"]["note_id"] == "555"
    assert out["preview"]["parent_comment_id"] == 555


def test_propose_reply_token_is_deterministic_per_payload():
    a = mcp_server._dispatch(
        "propose_reply",
        {"kind": "post", "post_id": "1", "parent_comment_id": "2", "body": "hi"},
    )
    mcp_server._proposals.clear()
    b = mcp_server._dispatch(
        "propose_reply",
        {"kind": "post", "post_id": "1", "parent_comment_id": "2", "body": "hi"},
    )
    assert a["token"] == b["token"]


def test_confirm_reply_unknown_token_raises():
    with pytest.raises(ValueError, match="unknown or expired"):
        mcp_server._dispatch("confirm_reply", {"token": "deadbeefdeadbeef"})


def test_confirm_reply_expired_token_raises():
    out = mcp_server._dispatch(
        "propose_reply",
        {"kind": "post", "post_id": "1", "parent_comment_id": "2", "body": "x"},
    )
    mcp_server._proposals[out["token"]]["expires"] = 0  # force expiry
    with pytest.raises(ValueError, match="unknown or expired"):
        mcp_server._dispatch("confirm_reply", {"token": out["token"]})


def test_confirm_reply_post_invokes_post_reply(monkeypatch):
    """confirm_reply should call post_reply with the stored payload + dry_run=False."""
    out = mcp_server._dispatch(
        "propose_reply",
        {"kind": "post", "post_id": "111", "parent_comment_id": "222", "body": "ok"},
    )
    token = out["token"]

    captured: dict = {}

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_create():
        return _FakeClient()

    def _fake_post_reply(client, **kw):
        captured.update(kw)
        return {"id": 999, "created_at": "now"}

    monkeypatch.setattr("substack_ops.client.SubstackClient.create", staticmethod(_fake_create))
    monkeypatch.setattr("substack_ops.reply_engine.base.post_reply", _fake_post_reply)

    res = mcp_server._dispatch("confirm_reply", {"token": token})
    assert res["token"] == token
    assert res["result"] == {"id": 999, "created_at": "now"}
    assert captured["post_id"] == 111
    assert captured["parent_id"] == 222
    assert captured["body"] == "ok"
    assert captured["dry_run"] is False
    assert captured["mode"] == "mcp:confirm_reply"
    assert token not in mcp_server._proposals  # consumed


def test_confirm_reply_note_invokes_post_note_reply(monkeypatch):
    out = mcp_server._dispatch(
        "propose_reply",
        {"kind": "note", "note_id": "777", "body": "agree"},
    )
    token = out["token"]

    captured: dict = {}

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        "substack_ops.client.SubstackClient.create", staticmethod(lambda: _FakeClient())
    )
    monkeypatch.setattr(
        "substack_ops.reply_engine.base.post_note_reply",
        lambda client, **kw: captured.update(kw) or {"id": 1},
    )

    mcp_server._dispatch("confirm_reply", {"token": token})
    assert captured["note_id"] == 777
    assert captured["parent_comment_id"] == 777
    assert captured["body"] == "agree"
    assert captured["mode"] == "mcp:confirm_reply"
