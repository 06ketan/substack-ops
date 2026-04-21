"""MCP server: tool registry + dispatcher (no live calls)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from substack_ops.audit import DEFAULT_AUDIT_PATH
from substack_ops.mcp.server import TOOLS, _dispatch, list_tool_names


def test_26_tools_registered():
    names = list_tool_names()
    assert len(names) == 26  # 19 parity + 4 unique + 3 MCP-native draft tools
    for spec in TOOLS.values():
        assert "description" in spec
        assert "input_schema" in spec


def test_required_tools_present():
    required = {
        "test_connection", "get_own_profile", "get_profile",
        "list_posts", "get_post", "get_post_by_id", "get_post_content",
        "search_posts", "list_notes", "list_comments", "get_feed",
        "publish_note", "reply_to_note", "comment_on_post",
        "react_to_post", "react_to_comment", "restack_post",
        "restack_note", "delete_comment",
        "bulk_draft_replies", "send_approved_drafts",
        "audit_search", "dedup_status",
        "get_unanswered_comments", "propose_reply", "confirm_reply",
    }
    assert required.issubset(set(list_tool_names()))


def test_dispatch_audit_search_offline(tmp_path: Path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    audit.write_text(json.dumps({"ts": "2026-04-21T00:00:00+00:00", "mode": "react_post", "result_status": "posted"}) + "\n")
    monkeypatch.setattr("substack_ops.audit.DEFAULT_AUDIT_PATH", audit)

    out = _dispatch("audit_search", {"kind": "react", "path": str(audit)})
    assert isinstance(out, list)


def test_dispatch_dedup_status_offline(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("substack_ops.dedup.DEFAULT_DB_PATH", tmp_path / "actions.db")
    out = _dispatch("dedup_status", {})
    assert "total" in out and "actions" in out


def test_dispatch_unknown_tool_raises():
    with pytest.raises(ValueError):
        _dispatch("nope_not_a_tool", {})
