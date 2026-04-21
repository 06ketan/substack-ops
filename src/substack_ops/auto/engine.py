"""Automation engine: trigger / action runner.

Triggers (poll-based):
- note_liked_by(other) — anyone reacted to one of your last N notes
- new_note_from(handle) — handle in watchlist published a new note
- new_follower(other) — somebody started following you

Actions (dedup-aware, audit-logged):
- react_to_their_latest_note(other)
- reply_to_their_latest_note(other, template)
- restack_note(note_id)
- follow(other)

Use:
    substack-ops auto presets             # list built-ins
    substack-ops auto run like-back       # one cycle, dry-run by default
    substack-ops auto daemon like-back    # loop forever
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml

from substack_ops.client import SubstackClient
from substack_ops.dedup import DedupDB, DuplicateActionError
from substack_ops.reply_engine.base import audit_log

PRESETS_PATH = Path(__file__).parent / "presets.yaml"
USER_RULES_DIR = Path.home() / ".config" / "substack-ops" / "auto"


def list_presets() -> list[dict[str, Any]]:
    data = yaml.safe_load(PRESETS_PATH.read_text())
    return data.get("presets", [])


def _load_rule(name: str) -> dict[str, Any]:
    """Resolve preset name OR path to a YAML rule file."""
    if "/" in name or name.endswith(".yaml") or name.endswith(".yml"):
        path = Path(name)
        if not path.exists():
            raise FileNotFoundError(f"rule file not found: {path}")
        return yaml.safe_load(path.read_text())
    for preset in list_presets():
        if preset["name"] == name:
            return preset
    user_path = USER_RULES_DIR / f"{name}.yaml"
    if user_path.exists():
        return yaml.safe_load(user_path.read_text())
    raise ValueError(
        f"unknown preset {name!r}. Try one of: {[p['name'] for p in list_presets()]}"
    )


def _trigger_note_liked_by(c: SubstackClient, limit: int) -> list[dict[str, Any]]:
    """Find users who reacted to your recent notes."""
    notes = c.list_notes(limit=10)
    out: list[dict[str, Any]] = []
    seen_users: set[int] = set()
    for n in notes:
        comment = (n.get("comment") or n)
        note_id = comment.get("id")
        if not note_id:
            continue
        thread = c.get_note_thread(note_id)
        item = (thread.get("item") or thread).get("comment") or {}
        for r in (item.get("reactions") or {}).get("emoji", []):
            for user in r.get("users") or []:
                uid = user.get("id")
                if not uid or uid in seen_users:
                    continue
                seen_users.add(uid)
                out.append(
                    {
                        "user_id": uid,
                        "user_name": user.get("name"),
                        "user_handle": user.get("handle"),
                        "note_id": note_id,
                    }
                )
                if len(out) >= limit:
                    return out
    return out


def _action_react_to_their_latest_note(
    c: SubstackClient,
    *,
    user: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    handle = user.get("user_handle")
    if not handle:
        return {"_skipped": "no handle"}
    profile = c.get_profile(handle)
    notes = profile.get("notes") or []
    if not notes:
        return {"_skipped": "no notes"}
    target_note_id = notes[0].get("id")
    if not target_note_id:
        return {"_skipped": "no note id"}
    target = f"note:{target_note_id}"
    if not dry_run:
        try:
            DedupDB().check(target_id=target, action="react_note", force=False)
        except DuplicateActionError:
            return {"_deduped": True, "target": target}
    res = c.react_to_note(note_id=target_note_id, dry_run=dry_run)
    if not dry_run:
        DedupDB().record(target_id=target, action="react_note")
    audit_log(
        {
            "mode": "auto:react_to_their_latest_note",
            "dry_run": dry_run,
            "target_user": handle,
            "target_id": str(target_note_id),
            "result_status": "dry_run" if dry_run else "posted",
        }
    )
    return res


def _action_reply_to_their_latest_note(
    c: SubstackClient,
    *,
    user: dict[str, Any],
    template_text: str,
    dry_run: bool,
) -> dict[str, Any]:
    from substack_ops.reply_engine.base import post_note_reply

    handle = user.get("user_handle")
    if not handle:
        return {"_skipped": "no handle"}
    profile = c.get_profile(handle)
    notes = profile.get("notes") or []
    if not notes:
        return {"_skipped": "no notes"}
    target_note_id = int(notes[0]["id"])
    return post_note_reply(
        c,
        note_id=target_note_id,
        parent_comment_id=target_note_id,
        body=template_text,
        dry_run=dry_run,
        mode="auto:reply_to_their_latest_note",
        original_author=handle,
        original_body=notes[0].get("body"),
    )


def run_once(*, name: str, dry_run: bool, limit: int = 20) -> dict[str, Any]:
    rule = _load_rule(name)
    counts = {"matched": 0, "executed": 0, "deduped": 0, "skipped": 0, "errors": 0}

    with SubstackClient.create() as c:
        if rule["trigger"] == "note_liked_by":
            users = _trigger_note_liked_by(c, limit=limit)
            counts["matched"] = len(users)
            template = rule.get("template_text") or "Appreciate the read 🙏"
            for user in users:
                try:
                    if rule["action"] == "react_to_their_latest_note":
                        res = _action_react_to_their_latest_note(c, user=user, dry_run=dry_run)
                    elif rule["action"] == "reply_to_their_latest_note":
                        res = _action_reply_to_their_latest_note(
                            c, user=user, template_text=template, dry_run=dry_run
                        )
                    else:
                        counts["skipped"] += 1
                        continue
                    if res.get("_deduped"):
                        counts["deduped"] += 1
                    elif res.get("_skipped"):
                        counts["skipped"] += 1
                    else:
                        counts["executed"] += 1
                except Exception:  # noqa: BLE001
                    counts["errors"] += 1
        else:
            counts["skipped"] = -1
            counts["note"] = f"trigger {rule['trigger']!r} not yet implemented"
    return counts


def run_daemon(*, name: str, interval: int, dry_run: bool) -> None:
    cycles = 0
    try:
        while True:
            cycles += 1
            counts = run_once(name=name, dry_run=dry_run)
            print(f"[auto-daemon] cycle {cycles} ({name}, dry_run={dry_run}): {counts}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"[auto-daemon] stopped after {cycles} cycles")
