"""Shared primitives: comment iteration, rate limiting, audit logging, posting."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from substack_ops.client import SubstackClient

AUDIT_PATH = Path(".cache") / "audit.jsonl"


@dataclass
class CommentRef:
    """A flat handle on one comment in a post's comment tree."""

    post_id: int | str
    comment_id: int
    parent_id: int | None
    author: str
    body: str
    depth: int
    raw: dict[str, Any]

    @property
    def short(self) -> str:
        b = (self.body or "").replace("\n", " ").strip()
        return f"#{self.comment_id} {self.author}: {b[:120]}"


def walk_comments(
    post_id: int | str,
    comments: list[dict[str, Any]],
    *,
    skip_self_id: int | None = None,
    depth: int = 0,
    parent_id: int | None = None,
) -> Iterator[CommentRef]:
    """Yield every comment + reply, depth-first.

    `skip_self_id` skips comments authored by your own user_id (so we don't
    reply to ourselves).
    """
    for c in comments:
        author = c.get("name") or (c.get("user") or {}).get("name") or "?"
        author_uid = c.get("user_id") or (c.get("user") or {}).get("id")
        if skip_self_id is None or author_uid != skip_self_id:
            yield CommentRef(
                post_id=post_id,
                comment_id=c.get("id"),
                parent_id=parent_id,
                author=author,
                body=c.get("body") or "",
                depth=depth,
                raw=c,
            )
        children = c.get("children") or c.get("replies") or []
        if children:
            yield from walk_comments(
                post_id,
                children,
                skip_self_id=skip_self_id,
                depth=depth + 1,
                parent_id=c.get("id"),
            )


@dataclass
class RateLimiter:
    """Token-bucket-ish: at most 1 op per `seconds` with jitter."""

    seconds: float = 30.0
    jitter: float = 5.0
    _last: float = field(default=0.0, init=False)

    def wait(self) -> float:
        now = time.monotonic()
        gap = (self.seconds + random.uniform(0, self.jitter)) - (now - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()
        return max(gap, 0.0)


def audit_log(record: dict[str, Any], path: Path = AUDIT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now(timezone.utc).isoformat(), **record}
    with path.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def post_reply(
    client: SubstackClient,
    *,
    post_id: int | str,
    parent_id: int,
    body: str,
    dry_run: bool,
    mode: str,
    original_author: str | None = None,
    original_body: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Single point of egress for any post-comment reply.

    Routes through dedup (skipped on dry_run) and audit log. Live posts are
    deduped on (`post:{post_id}:reply:{parent_id}`, `comment_reply`).
    """
    from substack_ops.dedup import DedupDB, DuplicateActionError

    target = f"post:{post_id}:reply:{parent_id}"
    if not dry_run:
        try:
            DedupDB().check(target_id=target, action="comment_reply", force=force)
        except DuplicateActionError as exc:
            audit_log(
                {
                    "mode": mode,
                    "dry_run": False,
                    "post_id": str(post_id),
                    "parent_id": parent_id,
                    "result_status": "deduped",
                    "reply_body": body,
                    "error": str(exc),
                }
            )
            return {"_deduped": True, "error": str(exc)}

    result = client.post_comment_reply(
        post_id=post_id,
        body=body,
        parent_id=parent_id,
        dry_run=dry_run,
    )

    status = "dry_run" if dry_run else "posted"
    if not dry_run:
        DedupDB().record(target_id=target, action="comment_reply")

    audit_log(
        {
            "mode": mode,
            "dry_run": dry_run,
            "post_id": str(post_id),
            "parent_id": parent_id,
            "original_author": original_author,
            "original_body": (original_body or "")[:500],
            "reply_body": body,
            "result_status": status,
            "result": {k: v for k, v in result.items() if k in ("id", "created_at")} if not dry_run else None,
        }
    )
    return result


def post_note_reply(
    client: SubstackClient,
    *,
    note_id: int | str,
    parent_comment_id: int,
    body: str,
    dry_run: bool,
    mode: str,
    original_author: str | None = None,
    original_body: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Single point of egress for note replies. Dedup-aware + ancestor_path guardrail.

    The ancestor_path check catches the M2 bug where the wrong field name
    silently created orphan top-level notes instead of threaded replies.
    """
    from substack_ops.dedup import DedupDB, DuplicateActionError

    target = f"note:{note_id}:reply:{parent_comment_id}"
    if not dry_run:
        try:
            DedupDB().check(target_id=target, action="note_reply", force=force)
        except DuplicateActionError as exc:
            audit_log(
                {
                    "mode": mode,
                    "dry_run": False,
                    "note_id": str(note_id),
                    "parent_comment_id": parent_comment_id,
                    "reply_body": body,
                    "result_status": "deduped",
                    "error": str(exc),
                }
            )
            return {"_deduped": True, "error": str(exc)}

    result = client.post_note_reply(
        note_id=parent_comment_id,
        body=body,
        dry_run=dry_run,
    )

    status = "dry_run" if dry_run else "posted"
    new_id = result.get("id") if isinstance(result, dict) else None

    if not dry_run:
        DedupDB().record(target_id=target, action="note_reply")
        if new_id:
            try:
                check = client.http.get(
                    f"https://substack.com/api/v1/reader/comment/{new_id}"
                )
                payload = check.json() if check.status_code == 200 else {}
                ap = (payload.get("item") or payload).get("ancestor_path") or ""
                if not ap:
                    status = "orphaned"
            except Exception:
                pass

    audit_log(
        {
            "mode": mode,
            "dry_run": dry_run,
            "note_id": str(note_id),
            "parent_comment_id": parent_comment_id,
            "original_author": original_author,
            "original_body": (original_body or "")[:500],
            "reply_body": body,
            "result_status": status,
            "result": {k: v for k, v in (result or {}).items() if k in ("id", "created_at")} if not dry_run else None,
        }
    )
    return result
