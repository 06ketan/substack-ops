"""MCP stdio server for substack-ops.

26 tools wired to SubstackClient. The server uses the official `mcp` Python
SDK if available, otherwise falls back to a JSON-line dispatcher on stdin/stdout.

Tools:
  reads:    test_connection, get_own_profile, get_profile, list_posts, get_post,
            get_post_by_id, get_post_content, search_posts, list_notes,
            list_comments, get_feed
  writes:   publish_note, reply_to_note, comment_on_post, react_to_post,
            react_to_comment, restack_post, restack_note, delete_comment
  unique:   bulk_draft_replies, send_approved_drafts, audit_search, dedup_status
  draft:    get_unanswered_comments, propose_reply, confirm_reply
            (host LLM drafts, no API key needed)
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

_PROPOSAL_TTL = 300.0
_proposals: dict[str, dict[str, Any]] = {}


def _purge_expired() -> None:
    now = time.time()
    expired = [t for t, p in _proposals.items() if p["expires"] < now]
    for t in expired:
        _proposals.pop(t, None)


def _make_token(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]

TOOLS: dict[str, dict[str, Any]] = {
    "test_connection": {
        "description": (
            "Read-only. Verify the Substack session cookie works and return the "
            "authenticated user's id, handle, and primary publication. Call this "
            "first if other tools 401 or to confirm setup. No args."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    "get_own_profile": {
        "description": (
            "Read-only. Return the authenticated user's full profile (handle, name, "
            "bio, photo, subscriber count). Use for self-info; for other users call "
            "get_profile. No args."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    "get_profile": {
        "description": (
            "Read-only. Return any user's public profile by handle (the @-name from "
            "their Substack URL, e.g. 'paulgraham'). For your own profile use "
            "get_own_profile (faster, no handle needed)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "handle": {
                    "type": "string",
                    "description": "Substack handle without @, as it appears in their URL.",
                }
            },
            "required": ["handle"],
        },
    },
    "list_posts": {
        "description": (
            "Read-only. List posts from a publication (yours by default). For a "
            "single post by id/slug use get_post; for full HTML body use "
            "get_post_content; to find by keyword use search_posts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "description": "Max posts to return (1-100)."},
                "pub": {"type": "string", "description": "Publication URL (e.g. https://example.substack.com/). Omit to use the authed user's pub."},
                "sort": {"type": "string", "default": "new", "enum": ["new", "top"], "description": "'new' = chronological; 'top' = most popular."},
            },
        },
    },
    "get_post": {
        "description": (
            "Read-only. Return one post's metadata (title, slug, dates, reactions, "
            "comment count) by numeric id OR slug. For HTML body use "
            "get_post_content. For id-only callers prefer get_post_by_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string", "description": "Numeric post id (e.g. '193866852') or slug ('my-post-title')."},
                "pub": {"type": "string"},
            },
            "required": ["post_id"],
        },
    },
    "get_post_by_id": {
        "description": (
            "Read-only. Strict-typed variant of get_post that only accepts a numeric "
            "id (no slug). Use when you already have an integer id and want type "
            "safety; otherwise use get_post."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"post_id": {"type": "integer", "description": "Numeric Substack post id."}},
            "required": ["post_id"],
        },
    },
    "get_post_content": {
        "description": (
            "Read-only. Return a post's body. Auth-aware: returns full text for "
            "paywalled posts you have access to, otherwise only the free preview. "
            "Set as_markdown=true to convert HTML to Markdown for LLM context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "pub": {"type": "string"},
                "as_markdown": {"type": "boolean", "default": False, "description": "Convert HTML to Markdown."},
            },
            "required": ["post_id"],
        },
    },
    "search_posts": {
        "description": (
            "Read-only. Full-text search posts in a publication. Use for keyword "
            "discovery; for chronological browsing use list_posts. Returns titles + "
            "ids only (call get_post / get_post_content for details)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keywords (Substack-side full-text)."},
                "limit": {"type": "integer", "default": 10},
                "pub": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    "list_notes": {
        "description": (
            "Read-only. List the authenticated user's own published Notes "
            "(short-form, Twitter-like). For a comment thread on a post use "
            "list_comments. For replies under one note, fetch via the note id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 20}},
        },
    },
    "list_comments": {
        "description": (
            "Read-only. Return the full nested comment tree for a post (parent + "
            "replies, with author handle, body, date, reaction count). To find only "
            "the threads YOU haven't replied to yet, use get_unanswered_comments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "pub": {"type": "string"},
            },
            "required": ["post_id"],
        },
    },
    "get_feed": {
        "description": (
            "Read-only. Pull the reader feed you'd see in the Substack app. Use "
            "tab='for-you' for personalized, 'subscribed' for pubs you follow, or "
            "'category-{slug}' (e.g. 'category-tech') for a topic feed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tab": {"type": "string", "default": "for-you", "description": "'for-you' | 'subscribed' | 'category-{slug}'"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    "publish_note": {
        "description": (
            "WRITE. Publish a new top-level Note (short-form post). Defaults to "
            "dry_run=true (no network write); set dry_run=false to actually post. "
            "Idempotent via dedup hash on body. For a reply to an existing note use "
            "reply_to_note. For long-form posts, use Substack's editor (not exposed)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "body": {"type": "string", "description": "Note text. Plain text or simple markdown."},
                "dry_run": {"type": "boolean", "default": True, "description": "true (default) = preview only; false = actually publish."},
            },
            "required": ["body"],
        },
    },
    "reply_to_note": {
        "description": (
            "WRITE. Reply to an existing Note (any author's). Defaults to "
            "dry_run=true. Dedup-protected: replays of the same body to the same "
            "note are no-ops. For replies to a post comment, use propose_reply -> "
            "confirm_reply (which run through the same safety stack)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "Numeric id of the note you're replying under."},
                "body": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["note_id", "body"],
        },
    },
    "comment_on_post": {
        "description": (
            "WRITE. Add a NEW top-level comment under a post (not a reply to an "
            "existing comment). Defaults to dry_run=true. For replies to existing "
            "comments use propose_reply -> confirm_reply. Dedup-protected by "
            "(post_id, body) hash."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "body": {"type": "string"},
                "pub": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["post_id", "body"],
        },
    },
    "react_to_post": {
        "description": (
            "WRITE. Add (on=true, default) or remove (on=false) a reaction on a "
            "post. Defaults to ❤ and dry_run=true. For comment-level reactions use "
            "react_to_comment. Reactions are not deduped (Substack itself "
            "idempotent)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "reaction": {"type": "string", "default": "❤", "description": "Emoji glyph (❤, 👍, 🎉, etc)."},
                "on": {"type": "boolean", "default": True, "description": "true=add, false=remove."},
                "pub": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["post_id"],
        },
    },
    "react_to_comment": {
        "description": (
            "WRITE. React on a comment (default ❤). Set kind='post' for comments "
            "under a post (uses the publication host) or kind='note' for replies "
            "on a Note (uses substack.com). Defaults to dry_run=true."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "comment_id": {"type": "string"},
                "kind": {"type": "string", "default": "post", "enum": ["post", "note"]},
                "reaction": {"type": "string", "default": "❤"},
                "on": {"type": "boolean", "default": True},
                "pub": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["comment_id"],
        },
    },
    "restack_post": {
        "description": (
            "WRITE. Restack a post (Substack's reshare). Defaults to dry_run=true. "
            "Substack does NOT support unrestacking via the public API — once on, "
            "stays on. To restack a Note instead, use restack_note."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "on": {"type": "boolean", "default": True, "description": "Note: off (false) is not supported by Substack — will be a no-op."},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["post_id"],
        },
    },
    "restack_note": {
        "description": (
            "WRITE. Restack a Note. Defaults to dry_run=true. Like restack_post, "
            "Substack does not support unrestacking. For posts use restack_post."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string"},
                "on": {"type": "boolean", "default": True},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["note_id"],
        },
    },
    "delete_comment": {
        "description": (
            "DESTRUCTIVE WRITE. Delete one of YOUR own comments (or one on your "
            "publication if you're the owner). Cannot be undone. Set kind='post' "
            "to delete a post comment (uses pub host) or kind='note' for a note "
            "reply. Defaults to dry_run=true — you must explicitly set false."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "comment_id": {"type": "string"},
                "kind": {"type": "string", "default": "post", "enum": ["post", "note"]},
                "pub": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["comment_id"],
        },
    },
    # ------- substack-ops unique tools -------
    "bulk_draft_replies": {
        "description": (
            "WRITE TO LOCAL FILE (no Substack call). Generate reply drafts for "
            "every comment on a post (kind='post') or every reply on a note "
            "(kind='note') using the daemon-path LLM (host CLI: claude / "
            "cursor-agent / codex on PATH, or SUBSTACK_OPS_LLM_CMD). Output is a "
            "JSONL drafts file with action='proposed' per row; review, edit "
            "action to 'approved' or 'rejected', then send via send_approved_drafts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["post", "note"], "default": "post"},
                "id": {"type": "string", "description": "post_id or note_id matching kind."},
                "out": {"type": "string", "default": "drafts.json"},
                "model": {"type": "string", "description": "Optional model hint passed to the host CLI."},
            },
            "required": ["id"],
        },
    },
    "send_approved_drafts": {
        "description": (
            "WRITE. Sequentially post every entry in a drafts.json file where "
            "action=='approved'. Skips proposed/rejected/already-deduped rows. "
            "Honors rate_seconds throttle. Defaults dry_run=true; set false to "
            "actually post. Use force=true to bypass dedup (rare; reposts a "
            "previously-sent reply)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "drafts_path": {"type": "string", "description": "Path to drafts.json produced by bulk_draft_replies."},
                "dry_run": {"type": "boolean", "default": True},
                "rate_seconds": {"type": "number", "default": 30, "description": "Min seconds between posts."},
                "force": {"type": "boolean", "default": False, "description": "Bypass dedup. Use sparingly."},
            },
            "required": ["drafts_path"],
        },
    },
    "audit_search": {
        "description": (
            "Read-only. Query the local audit.jsonl log of every write this server "
            "has performed (or attempted). Filters compose with AND. Use to debug "
            "'did I post that?' or to pull rate-limit history. For a quick count "
            "summary use dedup_status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "description": "e.g. 'reply', 'reaction', 'restack', 'note'"},
                "target": {"type": "string", "description": "post_id / note_id / comment_id substring."},
                "status": {"type": "string", "enum": ["ok", "error", "dry_run", "deduped"]},
                "since": {"type": "string", "description": "ISO-8601 timestamp or relative ('7d', '24h')."},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    "dedup_status": {
        "description": (
            "Read-only. Return counts from the local dedup SQLite DB (one row per "
            "successful write, keyed by content hash). Quick health check; for "
            "filtered details use audit_search. No args."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    # ------- MCP-native draft loop (host LLM does the drafting) -------
    "get_unanswered_comments": {
        "description": (
            "Read-only. Return comments on a post where the authenticated user has "
            "NOT yet replied (filters out the entire branch if you've replied "
            "anywhere in the ancestry). This is the canonical worklist tool: read "
            "each, draft a reply in your own context, then propose_reply -> "
            "confirm_reply per item. For the full unfiltered tree use list_comments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "pub": {"type": "string"},
                "limit": {"type": "integer", "default": 50, "description": "Max unanswered comments to return."},
            },
            "required": ["post_id"],
        },
    },
    "propose_reply": {
        "description": (
            "STAGE A WRITE (no Substack call yet). Validate a reply, compute its "
            "dedup hash, build the exact payload, store it under a token, return "
            "the token + preview. Show the preview to the user. On approval, call "
            "confirm_reply with the same token. Tokens expire in 5 minutes. "
            "kind='post' requires post_id + parent_comment_id (for replies under a "
            "comment); kind='note' requires note_id. For new top-level post "
            "comments use comment_on_post."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["post", "note"], "default": "post"},
                "post_id": {"type": "string", "description": "Required for kind='post'."},
                "note_id": {"type": "string", "description": "Required for kind='note'."},
                "parent_comment_id": {"type": "string", "description": "The comment id you're replying under. Required for kind='post'."},
                "body": {"type": "string", "description": "The reply text the host LLM drafted."},
                "pub": {"type": "string"},
            },
            "required": ["body"],
        },
    },
    "confirm_reply": {
        "description": (
            "EXECUTE the staged write. Look up the token from propose_reply, post "
            "to Substack, log to audit.jsonl, persist dedup row. Idempotent: if "
            "the same content was already sent, returns {deduped: true} without "
            "re-posting. Use force=true to bypass dedup (rare). Tokens are "
            "single-use and expire 5 min after propose_reply."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "token": {"type": "string", "description": "Opaque token returned by propose_reply."},
                "force": {"type": "boolean", "default": False, "description": "Bypass dedup. Use only when you intentionally want to re-send."},
            },
            "required": ["token"],
        },
    },
}


def list_tool_names() -> list[str]:
    return list(TOOLS.keys())


def _dispatch(name: str, args: dict[str, Any]) -> Any:
    """Dispatch one tool call to the underlying client/audit/dedup."""
    if name not in TOOLS:
        raise ValueError(f"unknown tool: {name}")

    from substack_ops.audit import search_audit
    from substack_ops.client import SubstackClient
    from substack_ops.dedup import DedupDB

    if name == "audit_search":
        return search_audit(
            kind=args.get("kind"),
            target=args.get("target"),
            status=args.get("status"),
            since=args.get("since"),
            limit=args.get("limit", 50),
        )
    if name == "dedup_status":
        return DedupDB().status()

    if name == "propose_reply":
        return _propose_reply(args)
    if name == "confirm_reply":
        return _confirm_reply(args)

    if name == "bulk_draft_replies":
        from substack_ops.reply_engine.ai_bulk import generate_drafts, generate_note_drafts

        out = Path(args.get("out") or "drafts.json")
        if args.get("kind", "post") == "note":
            n = generate_note_drafts(note_id=args["id"], out=out, model=args.get("model"))
        else:
            n = generate_drafts(post_id=args["id"], out=out, model=args.get("model"))
        return {"drafts": n, "path": str(out)}

    if name == "send_approved_drafts":
        from substack_ops.reply_engine.ai_bulk import send_drafts

        return send_drafts(
            drafts_path=Path(args["drafts_path"]),
            dry_run=args.get("dry_run", True),
            rate_seconds=args.get("rate_seconds", 30.0),
            force=args.get("force", False),
        )

    with SubstackClient.create() as c:
        if name == "test_connection":
            return c.get_my_profile()
        if name == "get_own_profile":
            return c.get_my_profile()
        if name == "get_profile":
            return c.get_profile(args["handle"])
        if name == "list_posts":
            return c.list_posts(
                limit=args.get("limit", 20),
                sorting=args.get("sort", "new"),
                pub=args.get("pub"),
            )
        if name == "get_post":
            return c.get_post(args["post_id"], pub=args.get("pub"))
        if name == "get_post_by_id":
            return c.get_post(args["post_id"])
        if name == "get_post_content":
            html = c.get_post_content(args["post_id"], pub=args.get("pub"))
            if html and args.get("as_markdown"):
                from markdownify import markdownify

                return markdownify(html, heading_style="ATX")
            return html
        if name == "search_posts":
            return c.search_posts(
                query=args["query"],
                limit=args.get("limit", 10),
                pub=args.get("pub"),
            )
        if name == "list_notes":
            return c.list_notes(limit=args.get("limit", 20))
        if name == "list_comments":
            return c.get_comments(args["post_id"], pub=args.get("pub"))
        if name == "get_unanswered_comments":
            data = c.get_comments(args["post_id"], pub=args.get("pub"))
            items = data.get("comments") or data.get("items") or []
            my_id = c.cfg.user_id
            unanswered: list[dict[str, Any]] = []

            def _has_my_reply(children: list[dict[str, Any]]) -> bool:
                for ch in children or []:
                    if ch.get("user_id") == my_id:
                        return True
                    if _has_my_reply(ch.get("children") or []):
                        return True
                return False

            def _walk(comments: list[dict[str, Any]]) -> None:
                for cmt in comments:
                    if cmt.get("user_id") == my_id:
                        _walk(cmt.get("children") or [])
                        continue
                    if not _has_my_reply(cmt.get("children") or []):
                        unanswered.append(
                            {
                                "id": cmt.get("id"),
                                "body": cmt.get("body"),
                                "name": cmt.get("name"),
                                "handle": cmt.get("handle"),
                                "user_id": cmt.get("user_id"),
                                "date": cmt.get("date"),
                                "depth": cmt.get("ancestor_path", "").count(".") if cmt.get("ancestor_path") else 0,
                            }
                        )
                    _walk(cmt.get("children") or [])

            _walk(items)
            return unanswered[: args.get("limit", 50)]
        if name == "get_feed":
            return c.get_feed(tab=args.get("tab", "for-you"), limit=args.get("limit", 20))
        if name == "publish_note":
            return c.publish_note(body=args["body"], dry_run=args.get("dry_run", True))
        if name == "reply_to_note":
            from substack_ops.reply_engine.base import post_note_reply

            note_id = int(args["note_id"])
            return post_note_reply(
                c,
                note_id=note_id,
                parent_comment_id=note_id,
                body=args["body"],
                dry_run=args.get("dry_run", True),
                mode="mcp:reply_to_note",
            )
        if name == "comment_on_post":
            return c.add_comment(
                post_id=args["post_id"],
                body=args["body"],
                pub=args.get("pub"),
                dry_run=args.get("dry_run", True),
            )
        if name == "react_to_post":
            return c.react_to_post(
                post_id=args["post_id"],
                reaction=args.get("reaction", "❤"),
                on=args.get("on", True),
                pub=args.get("pub"),
                dry_run=args.get("dry_run", True),
            )
        if name == "react_to_comment":
            return c.react_to_comment(
                comment_id=args["comment_id"],
                kind=args.get("kind", "post"),
                reaction=args.get("reaction", "❤"),
                on=args.get("on", True),
                pub=args.get("pub"),
                dry_run=args.get("dry_run", True),
            )
        if name == "restack_post":
            return c.restack_post(
                post_id=args["post_id"],
                on=args.get("on", True),
                dry_run=args.get("dry_run", True),
            )
        if name == "restack_note":
            return c.restack_note(
                note_id=args["note_id"],
                on=args.get("on", True),
                dry_run=args.get("dry_run", True),
            )
        if name == "delete_comment":
            return c.delete_comment(
                comment_id=args["comment_id"],
                kind=args.get("kind", "post"),
                pub=args.get("pub"),
                dry_run=args.get("dry_run", True),
            )

    raise ValueError(f"unknown tool: {name}")


def _propose_reply(args: dict[str, Any]) -> dict[str, Any]:
    """Build a dry-run preview, store it under a token, return token + preview."""
    _purge_expired()
    kind = (args.get("kind") or "post").lower()
    body = args["body"]
    if kind == "note":
        note_id = args.get("note_id") or args.get("parent_comment_id")
        if not note_id:
            raise ValueError("propose_reply(kind=note) requires note_id or parent_comment_id")
        payload = {
            "kind": "note",
            "note_id": str(note_id),
            "parent_comment_id": int(args.get("parent_comment_id") or note_id),
            "body": body,
        }
    else:
        post_id = args.get("post_id")
        parent = args.get("parent_comment_id")
        if not post_id:
            raise ValueError("propose_reply(kind=post) requires post_id")
        if not parent:
            raise ValueError(
                "propose_reply(kind=post) requires parent_comment_id "
                "(use comment_on_post for new top-level comments)"
            )
        payload = {
            "kind": "post",
            "post_id": str(post_id),
            "parent_comment_id": int(parent),
            "body": body,
            "pub": args.get("pub"),
        }
    token = _make_token(payload)
    _proposals[token] = {
        "payload": payload,
        "expires": time.time() + _PROPOSAL_TTL,
        "created": time.time(),
    }
    return {
        "token": token,
        "expires_in": int(_PROPOSAL_TTL),
        "preview": payload,
    }


def _confirm_reply(args: dict[str, Any]) -> dict[str, Any]:
    """Look up token, post for real via reply_engine.base (dedup + audit + ancestor_path)."""
    _purge_expired()
    token = args["token"]
    proposal = _proposals.get(token)
    if not proposal:
        raise ValueError(
            f"unknown or expired token: {token} (proposals expire after "
            f"{int(_PROPOSAL_TTL)}s)"
        )
    payload = proposal["payload"]
    force = bool(args.get("force", False))

    from substack_ops.client import SubstackClient
    from substack_ops.reply_engine.base import post_note_reply, post_reply

    with SubstackClient.create() as c:
        if payload["kind"] == "note":
            res = post_note_reply(
                c,
                note_id=int(payload["note_id"]),
                parent_comment_id=int(payload["parent_comment_id"]),
                body=payload["body"],
                dry_run=False,
                force=force,
                mode="mcp:confirm_reply",
            )
        else:
            res = post_reply(
                c,
                post_id=int(payload["post_id"]),
                parent_id=int(payload["parent_comment_id"]),
                body=payload["body"],
                dry_run=False,
                force=force,
                mode="mcp:confirm_reply",
                pub=payload.get("pub"),
            )

    _proposals.pop(token, None)
    return {"token": token, "result": res}


def serve() -> None:
    """Run an MCP stdio server. Falls back to a minimal JSON-line dispatcher
    so the server still works without the `mcp` SDK installed (handy for tests
    and CLI scripting).
    """
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[import-untyped]
    except ImportError:
        _fallback_dispatcher()
        return

    server = FastMCP("substack-ops")
    for name, spec in TOOLS.items():
        _register(server, name, spec)
    server.run()


def _register(server: Any, name: str, spec: dict[str, Any]) -> None:
    """Register a tool with FastMCP. We use a closure over `name`."""

    @server.tool(name=name, description=spec["description"])
    def _tool(**kwargs: Any) -> Any:
        return _dispatch(name, kwargs)

    return _tool  # type: ignore[no-any-return]


def _fallback_dispatcher() -> None:
    """One JSON request per stdin line, one JSON response per stdout line.

    Request:  {"tool": "list_posts", "args": {"limit": 5}}
    Response: {"ok": true, "result": [...]} / {"ok": false, "error": "..."}
    Special:  {"tool": "__list__"} returns tool names.
    """
    import sys

    sys.stderr.write(
        "[substack-ops mcp] running fallback dispatcher (install `mcp` SDK for stdio MCP).\n"
    )
    sys.stderr.flush()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(json.dumps({"ok": False, "error": f"bad json: {exc}"}))
            sys.stdout.flush()
            continue
        tool = req.get("tool")
        if tool == "__list__":
            print(json.dumps({"ok": True, "result": list_tool_names()}))
            sys.stdout.flush()
            continue
        try:
            result = _dispatch(tool, req.get("args") or {})
            print(json.dumps({"ok": True, "result": result}, default=str, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": repr(exc)}))
        sys.stdout.flush()


if os.environ.get("SUBSTACK_OPS_MCP_DEBUG"):
    print("[mcp] tools:", ", ".join(TOOLS.keys()))
