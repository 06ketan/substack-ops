"""Regression tests for the M2 bug where ai_bulk:note ran twice and posted
31 dup replies. SQLite dedup DB is the fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from substack_ops.dedup import DedupDB, DuplicateActionError


def test_check_first_call_is_noop(tmp_path: Path):
    db = DedupDB(tmp_path / "actions.db")
    db.check(target_id="post:42:reply:7", action="comment_reply")


def test_record_then_check_raises(tmp_path: Path):
    db = DedupDB(tmp_path / "actions.db")
    db.record(target_id="post:42:reply:7", action="comment_reply")
    with pytest.raises(DuplicateActionError):
        db.check(target_id="post:42:reply:7", action="comment_reply")


def test_force_bypasses_dedup(tmp_path: Path):
    db = DedupDB(tmp_path / "actions.db")
    db.record(target_id="post:42:reply:7", action="comment_reply")
    db.check(target_id="post:42:reply:7", action="comment_reply", force=True)


def test_record_idempotent_on_unique_violation(tmp_path: Path):
    db = DedupDB(tmp_path / "actions.db")
    db.record(target_id="x", action="react_post")
    db.record(target_id="x", action="react_post")
    stats = db.status()
    assert stats["actions"]["react_post"] == 1


def test_status_groups_by_action(tmp_path: Path):
    db = DedupDB(tmp_path / "actions.db")
    db.record(target_id="a", action="react_post")
    db.record(target_id="b", action="react_post")
    db.record(target_id="a", action="restack_post")
    stats = db.status()
    assert stats["actions"] == {"react_post": 2, "restack_post": 1}
    assert stats["total"] == 3


def test_different_targets_dont_collide(tmp_path: Path):
    db = DedupDB(tmp_path / "actions.db")
    db.record(target_id="post:1:reply:1", action="comment_reply")
    db.check(target_id="post:1:reply:2", action="comment_reply")
    db.check(target_id="post:2:reply:1", action="comment_reply")
