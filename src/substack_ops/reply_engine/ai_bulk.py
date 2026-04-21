"""Bulk drafts.json workflow.

Step 1: `reply bulk <post_id> --out drafts.json`
        — generates drafts for every comment, written to a JSON file you edit.

Step 2: edit drafts.json, change `"action": "pending"` to `"approved"`
        (or `"skip"`) for each item. Optionally tweak `"draft"`.

Step 3: `reply bulk-send drafts.json`
        — posts only items where action == "approved".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from substack_ops.client import SubstackClient
from substack_ops.llm import LLM
from substack_ops.reply_engine.base import (
    RateLimiter,
    post_note_reply,
    post_reply,
    walk_comments,
)


def generate_drafts(
    *,
    post_id: int | str,
    out: Path,
    model: str | None = None,
) -> int:
    llm = LLM.from_env(model)
    if llm.provider == "none":
        raise RuntimeError(
            "ai_bulk needs an LLM. Install claude/cursor-agent/codex on PATH "
            "or set SUBSTACK_OPS_LLM_CMD='your-cli {prompt}'."
        )

    drafts: list[dict[str, Any]] = []
    with SubstackClient.create() as c:
        post_meta = c.get_post(post_id)
        post_title = post_meta.get("title")
        tree = c.get_comments(post_id)
        comments = tree.get("comments") or []
        my_uid = int(c.cfg.user_id)
        for ref in walk_comments(post_id, comments, skip_self_id=my_uid):
            try:
                draft = llm.draft(
                    comment_body=ref.body,
                    comment_author=ref.author,
                    post_title=post_title,
                )
            except Exception as exc:  # noqa: BLE001
                draft = f"<LLM error: {exc}>"
            drafts.append(
                {
                    "kind": "comment",
                    "comment_id": ref.comment_id,
                    "post_id": str(post_id),
                    "author": ref.author,
                    "depth": ref.depth,
                    "original": ref.body,
                    "draft": draft,
                    "action": "pending",  # change to "approved" or "skip"
                }
            )

    out.write_text(json.dumps(drafts, indent=2, ensure_ascii=False))
    return len(drafts)


def generate_note_drafts(
    *,
    note_id: int | str,
    out: Path,
    model: str | None = None,
) -> int:
    """Same as generate_drafts but for note replies.

    Notes use a different POST endpoint (/api/v1/comment/feed) and bodyJson
    structure, but drafting logic is identical.
    """
    llm = LLM.from_env(model)
    if llm.provider == "none":
        raise RuntimeError(
            "ai_bulk needs an LLM. Install claude/cursor-agent/codex on PATH "
            "or set SUBSTACK_OPS_LLM_CMD='your-cli {prompt}'."
        )

    drafts: list[dict[str, Any]] = []
    with SubstackClient.create() as c:
        thread = c.get_note_thread(note_id)
        note = (thread.get("item") or {}).get("comment") or {}
        note_body = note.get("body") or "(unknown note)"
        replies = c.get_note_replies(note_id)
        my_uid = int(c.cfg.user_id)

        for ref in walk_comments(note_id, replies, skip_self_id=my_uid):
            try:
                draft = llm.draft(
                    comment_body=ref.body,
                    comment_author=ref.author,
                    post_title=f"My note: {note_body[:80]}",
                )
            except Exception as exc:  # noqa: BLE001
                draft = f"<LLM error: {exc}>"
            drafts.append(
                {
                    "kind": "note",
                    "comment_id": ref.comment_id,
                    "note_id": str(note_id),
                    "parent_id": ref.parent_id,
                    "author": ref.author,
                    "depth": ref.depth,
                    "original": ref.body,
                    "draft": draft,
                    "action": "pending",
                }
            )

    out.write_text(json.dumps(drafts, indent=2, ensure_ascii=False))
    return len(drafts)


def send_drafts(
    *,
    drafts_path: Path,
    dry_run: bool,
    rate_seconds: float,
    force: bool = False,
) -> dict[str, int]:
    """Post any draft with action == 'approved'. Routes to comment vs note
    endpoint based on `kind` field. Dedup-aware via base.post_*_reply.
    """
    drafts = json.loads(drafts_path.read_text())
    counts = {
        "approved": 0,
        "skipped": 0,
        "pending": 0,
        "posted": 0,
        "deduped": 0,
        "orphaned": 0,
        "errors": 0,
    }

    with SubstackClient.create() as c:
        limiter = RateLimiter(seconds=rate_seconds)
        for d in drafts:
            action = (d.get("action") or "pending").lower()
            counts[action] = counts.get(action, 0) + 1
            if action != "approved":
                continue
            limiter.wait()
            try:
                kind = (d.get("kind") or "comment").lower()
                if kind == "note":
                    parent = int(d.get("comment_id"))
                    res = post_note_reply(
                        c,
                        note_id=d.get("note_id") or parent,
                        parent_comment_id=parent,
                        body=d["draft"],
                        dry_run=dry_run,
                        mode="ai_bulk:note",
                        original_author=d.get("author"),
                        original_body=d.get("original"),
                        force=force,
                    )
                    if isinstance(res, dict) and res.get("_deduped"):
                        counts["deduped"] += 1
                        continue
                else:
                    res = post_reply(
                        c,
                        post_id=d["post_id"],
                        parent_id=int(d["comment_id"]),
                        body=d["draft"],
                        dry_run=dry_run,
                        mode="ai_bulk",
                        original_author=d.get("author"),
                        original_body=d.get("original"),
                        force=force,
                    )
                    if isinstance(res, dict) and res.get("_deduped"):
                        counts["deduped"] += 1
                        continue
                counts["posted"] += 1
            except Exception:  # noqa: BLE001
                counts["errors"] += 1
    return counts
