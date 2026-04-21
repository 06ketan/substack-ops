"""Interactive per-comment review: AI drafts, you accept/edit/skip/quit."""

from __future__ import annotations

from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from substack_ops.client import SubstackClient
from substack_ops.llm import LLM
from substack_ops.reply_engine.base import (
    CommentRef,
    RateLimiter,
    post_reply,
    walk_comments,
)

console = Console()


def run_review(
    *,
    post_id: int | str,
    dry_run: bool,
    rate_seconds: float,
    model: str | None = None,
) -> list[dict[str, Any]]:
    llm = LLM.from_env(model)
    if llm.provider == "none":
        raise RuntimeError(
            "ai_review needs an LLM. Install claude/cursor-agent/codex on PATH "
            "or set SUBSTACK_OPS_LLM_CMD='your-cli {prompt}'.\n"
            "Tip: from your chat app, use the MCP propose_reply / confirm_reply tools instead."
        )

    results: list[dict[str, Any]] = []
    with SubstackClient.create() as c:
        post_meta = c.get_post(post_id)
        post_title = post_meta.get("title")
        tree = c.get_comments(post_id)
        comments = tree.get("comments") or []
        limiter = RateLimiter(seconds=rate_seconds, jitter=2.0)
        my_uid = int(c.cfg.user_id)
        refs: list[CommentRef] = list(walk_comments(post_id, comments, skip_self_id=my_uid))

        if not refs:
            console.print("[dim]no comments to reply to[/]")
            return results

        for i, ref in enumerate(refs, 1):
            console.print(
                Panel.fit(
                    f"[bold cyan]{ref.author}[/] [dim]#{ref.comment_id}[/]\n{ref.body}",
                    title=f"Comment {i}/{len(refs)} (depth {ref.depth})",
                )
            )
            try:
                draft = llm.draft(
                    comment_body=ref.body,
                    comment_author=ref.author,
                    post_title=post_title,
                )
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]LLM error:[/] {exc}")
                continue

            while True:
                console.print(Panel.fit(draft, title="Draft reply", border_style="green"))
                action = Prompt.ask(
                    "[a]ccept / [e]dit / [s]kip / [q]uit",
                    choices=["a", "e", "s", "q"],
                    default="s",
                ).lower()
                if action == "q":
                    return results
                if action == "s":
                    break
                if action == "e":
                    edited = typer.edit(draft)
                    if edited is not None:
                        draft = edited.strip()
                    continue
                if action == "a":
                    limiter.wait()
                    r = post_reply(
                        c,
                        post_id=post_id,
                        parent_id=ref.comment_id,
                        body=draft,
                        dry_run=dry_run,
                        mode="ai_review",
                        original_author=ref.author,
                        original_body=ref.body,
                    )
                    results.append(
                        {"comment_id": ref.comment_id, "reply": draft, "result": r}
                    )
                    if dry_run:
                        console.print("[yellow]dry run — not posted[/]")
                    else:
                        console.print("[green]posted[/]")
                    break
    return results
