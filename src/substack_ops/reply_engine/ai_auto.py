"""Fully automated AI replies. Gated behind --yes-i-mean-it.

Use with extreme care: hits your real account at rate-limited cadence.
Every action is in audit.jsonl regardless of outcome.
"""

from __future__ import annotations

from typing import Any

from substack_ops.client import SubstackClient
from substack_ops.llm import LLM
from substack_ops.reply_engine.base import (
    RateLimiter,
    post_reply,
    walk_comments,
)


def run_auto(
    *,
    post_id: int | str,
    dry_run: bool,
    rate_seconds: float,
    model: str | None = None,
) -> list[dict[str, Any]]:
    llm = LLM.from_env(model)
    if llm.provider == "none":
        raise RuntimeError(
            "ai_auto needs an LLM. Install claude/cursor-agent/codex on PATH "
            "or set SUBSTACK_OPS_LLM_CMD='your-cli {prompt}'."
        )

    results: list[dict[str, Any]] = []
    with SubstackClient.create() as c:
        post_meta = c.get_post(post_id)
        post_title = post_meta.get("title")
        tree = c.get_comments(post_id)
        comments = tree.get("comments") or []
        limiter = RateLimiter(seconds=rate_seconds)
        my_uid = int(c.cfg.user_id)
        for ref in walk_comments(post_id, comments, skip_self_id=my_uid):
            try:
                draft = llm.draft(
                    comment_body=ref.body,
                    comment_author=ref.author,
                    post_title=post_title,
                )
            except Exception as exc:  # noqa: BLE001
                results.append({"comment_id": ref.comment_id, "error": str(exc)})
                continue
            limiter.wait()
            r = post_reply(
                c,
                post_id=post_id,
                parent_id=ref.comment_id,
                body=draft,
                dry_run=dry_run,
                mode="ai_auto",
                original_author=ref.author,
                original_body=ref.body,
            )
            results.append({"comment_id": ref.comment_id, "draft": draft, "result": r})
    return results
