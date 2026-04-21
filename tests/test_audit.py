"""Audit log search."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from substack_ops.audit import iter_audit, parse_duration, search_audit


def test_parse_duration():
    assert parse_duration("7d") == timedelta(days=7)
    assert parse_duration("24h") == timedelta(hours=24)
    assert parse_duration("30m") == timedelta(minutes=30)
    assert parse_duration("45s") == timedelta(seconds=45)
    assert parse_duration("2w") == timedelta(weeks=2)
    with pytest.raises(ValueError):
        parse_duration("nope")


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "audit.jsonl"
    with p.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return p


def test_iter_audit_skips_blank_and_bad_lines(tmp_path: Path):
    p = tmp_path / "audit.jsonl"
    p.write_text('{"a":1}\n\n{not json}\n{"b":2}\n')
    rows = iter_audit(p)
    assert rows == [{"a": 1}, {"b": 2}]


def test_search_audit_filter_by_kind(tmp_path: Path):
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"ts": now, "mode": "ai_bulk", "result_status": "posted"},
        {"ts": now, "mode": "ai_bulk:note", "result_status": "posted"},
        {"ts": now, "mode": "react_post", "result_status": "posted"},
    ]
    p = _write(tmp_path, rows)
    out = search_audit(kind="ai_bulk", path=p)
    assert len(out) == 2
    out2 = search_audit(kind="react", path=p)
    assert len(out2) == 1


def test_search_audit_status_and_target(tmp_path: Path):
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"ts": now, "mode": "ai_bulk:note", "note_id": "111", "result_status": "posted"},
        {"ts": now, "mode": "ai_bulk:note", "note_id": "222", "result_status": "dry_run"},
    ]
    p = _write(tmp_path, rows)
    out = search_audit(status="posted", path=p)
    assert len(out) == 1 and out[0]["note_id"] == "111"
    out2 = search_audit(target="222", path=p)
    assert len(out2) == 1


def test_search_audit_since(tmp_path: Path):
    now = datetime.now(timezone.utc)
    rows = [
        {"ts": (now - timedelta(days=10)).isoformat(), "mode": "x", "result_status": "posted"},
        {"ts": now.isoformat(), "mode": "x", "result_status": "posted"},
    ]
    p = _write(tmp_path, rows)
    out = search_audit(since="7d", path=p)
    assert len(out) == 1
