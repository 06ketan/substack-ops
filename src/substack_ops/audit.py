"""Audit log search."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_AUDIT_PATH = Path(".cache") / "audit.jsonl"


_DURATION_RE = re.compile(r"^(\d+)([smhdw])$")
_DURATION_UNITS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 60 * 60 * 24,
    "w": 60 * 60 * 24 * 7,
}


def parse_duration(s: str) -> timedelta:
    """`7d`, `24h`, `30m`, `45s`, `2w`."""
    m = _DURATION_RE.match(s.strip().lower())
    if not m:
        raise ValueError(f"bad duration: {s!r} (try 7d, 24h, 30m)")
    n, u = int(m.group(1)), m.group(2)
    return timedelta(seconds=n * _DURATION_UNITS[u])


def iter_audit(path: Path = DEFAULT_AUDIT_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def search_audit(
    *,
    kind: str | None = None,
    target: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = 50,
    path: Path = DEFAULT_AUDIT_PATH,
) -> list[dict[str, Any]]:
    rows = iter_audit(path)
    cutoff: datetime | None = None
    if since:
        cutoff = datetime.now(timezone.utc) - parse_duration(since)

    def keep(row: dict[str, Any]) -> bool:
        if kind:
            mode = row.get("mode") or ""
            if not mode.startswith(kind) and kind not in mode:
                return False
        if status and row.get("result_status") != status:
            return False
        if target:
            joined = " ".join(
                str(row.get(k) or "")
                for k in ("target_id", "post_id", "note_id", "parent_comment_id", "parent_id")
            )
            if target not in joined:
                return False
        if cutoff:
            ts = row.get("ts")
            if not ts:
                return False
            try:
                row_ts = datetime.fromisoformat(ts)
            except ValueError:
                return False
            if row_ts < cutoff:
                return False
        return True

    matched = [r for r in rows if keep(r)]
    matched.reverse()
    return matched[:limit]
