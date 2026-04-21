"""SQLite dedup DB for write actions.

Lives at `.cache/actions.db`. Every write op (`react_*`, `restack_*`,
`add_comment`, `delete_comment`, `post_comment_reply`, `post_note_reply`)
checks dedup first; refuses with `DuplicateActionError` unless `--force`.

This is the regression patch for the audit-log bug from M2 where
ai_bulk:note ran twice and posted 31 dup replies.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(".cache") / "actions.db"


class DuplicateActionError(RuntimeError):
    pass


class DedupDB:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id TEXT NOT NULL,
                action TEXT NOT NULL,
                posted_at TEXT NOT NULL,
                audit_ref TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS actions_unique
                ON actions(target_id, action);
            """
        )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> DedupDB:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def has(self, *, target_id: str, action: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM actions WHERE target_id = ? AND action = ? LIMIT 1",
            (target_id, action),
        )
        return cur.fetchone() is not None

    def check(self, *, target_id: str, action: str, force: bool = False) -> None:
        """Raise DuplicateActionError if already-posted unless force."""
        if force:
            return
        if self.has(target_id=target_id, action=action):
            raise DuplicateActionError(
                f"already executed {action!r} on {target_id!r} "
                f"(use --force to override; check audit.jsonl first)"
            )

    def record(self, *, target_id: str, action: str, audit_ref: str | None = None) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        try:
            self._conn.execute(
                "INSERT INTO actions(target_id, action, posted_at, audit_ref) "
                "VALUES (?, ?, ?, ?)",
                (target_id, action, ts, audit_ref),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            pass

    def status(self) -> dict[str, Any]:
        cur = self._conn.execute(
            "SELECT action, COUNT(*) FROM actions GROUP BY action ORDER BY 2 DESC"
        )
        actions = {row[0]: row[1] for row in cur.fetchall()}
        total = sum(actions.values())
        return {"path": str(self.path), "total": total, "actions": actions}

    def since(self, duration: timedelta) -> list[dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - duration).isoformat()
        cur = self._conn.execute(
            "SELECT target_id, action, posted_at, audit_ref FROM actions "
            "WHERE posted_at >= ? ORDER BY posted_at DESC",
            (cutoff,),
        )
        return [
            {"target_id": r[0], "action": r[1], "posted_at": r[2], "audit_ref": r[3]}
            for r in cur.fetchall()
        ]
