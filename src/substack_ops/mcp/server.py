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
        "description": "Verify Substack auth + return who you are.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    "get_own_profile": {
        "description": "Your Substack profile.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    "get_profile": {
        "description": "Public profile for a user handle.",
        "input_schema": {
            "type": "object",
            "properties": {"handle": {"type": "string"}},
            "required": ["handle"],
        },
    },
    "list_posts": {
        "description": "List posts from a publication (yours unless --pub).",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
                "pub": {"type": "string"},
                "sort": {"type": "string", "default": "new"},
            },
        },
    },
    "get_post": {
        "description": "Post metadata by id or slug.",
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "pub": {"type": "string"},
            },
            "required": ["post_id"],
        },
    },
    "get_post_by_id": {
        "description": "Post metadata by numeric id only.",
        "input_schema": {
            "type": "object",
            "properties": {"post_id": {"type": "integer"}},
            "required": ["post_id"],
        },
    },
    "get_post_content": {
        "description": "HTML body of a post (auth-aware for paywalled).",
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "pub": {"type": "string"},
                "as_markdown": {"type": "boolean", "default": False},
            },
            "required": ["post_id"],
        },
    },
    "search_posts": {
        "description": "Search posts in a publication.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
                "pub": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    "list_notes": {
        "description": "List notes by the current user.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 20}},
        },
    },
    "list_comments": {
        "description": "Comment tree for a post.",
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
        "description": "Reader feed (for-you / subscribed / category-{slug}).",
        "input_schema": {
            "type": "object",
            "properties": {
                "tab": {"type": "string", "default": "for-you"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    "publish_note": {
        "description": "Publish a top-level note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "body": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["body"],
        },
    },
    "reply_to_note": {
        "description": "Reply to a note (dedup-aware).",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string"},
                "body": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["note_id", "body"],
        },
    },
    "comment_on_post": {
        "description": "Top-level comment on a post.",
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
        "description": "React (or unreact with on=false) to a post.",
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "reaction": {"type": "string", "default": "❤"},
                "on": {"type": "boolean", "default": True},
                "pub": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["post_id"],
        },
    },
    "react_to_comment": {
        "description": "React to a comment (kind=post|note).",
        "input_schema": {
            "type": "object",
            "properties": {
                "comment_id": {"type": "string"},
                "kind": {"type": "string", "default": "post"},
                "reaction": {"type": "string", "default": "❤"},
                "on": {"type": "boolean", "default": True},
                "pub": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["comment_id"],
        },
    },
    "restack_post": {
        "description": "Restack a post.",
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "on": {"type": "boolean", "default": True},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["post_id"],
        },
    },
    "restack_note": {
        "description": "Restack a note.",
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
        "description": "Delete a comment (kind=post uses pub host; kind=note uses substack.com).",
        "input_schema": {
            "type": "object",
            "properties": {
                "comment_id": {"type": "string"},
                "kind": {"type": "string", "default": "post"},
                "pub": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["comment_id"],
        },
    },
    # ------- substack-ops unique tools -------
    "bulk_draft_replies": {
        "description": "Generate AI reply drafts for every comment on a post (or note). Writes drafts.json.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["post", "note"], "default": "post"},
                "id": {"type": "string"},
                "out": {"type": "string", "default": "drafts.json"},
                "model": {"type": "string"},
            },
            "required": ["id"],
        },
    },
    "send_approved_drafts": {
        "description": "Post only the entries in a drafts.json file marked action=approved.",
        "input_schema": {
            "type": "object",
            "properties": {
                "drafts_path": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
                "rate_seconds": {"type": "number", "default": 30},
                "force": {"type": "boolean", "default": False},
            },
            "required": ["drafts_path"],
        },
    },
    "audit_search": {
        "description": "Search the .cache/audit.jsonl log.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "target": {"type": "string"},
                "status": {"type": "string"},
                "since": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    "dedup_status": {
        "description": "Counts in the dedup SQLite DB.",
        "input_schema": {"type": "object", "properties": {}},
    },
    # ------- MCP-native draft loop (host LLM does the drafting) -------
    "get_unanswered_comments": {
        "description": (
            "Return comments on a post where the authed user has NOT yet replied. "
            "Use this as the worklist: read each, draft a reply in your own context, "
            "then call propose_reply -> confirm_reply for each one you want to send."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string"},
                "pub": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["post_id"],
        },
    },
    "propose_reply": {
        "description": (
            "Dry-run a reply. Returns a token + dedup hash + the would-be payload. "
            "NO Substack write. Show the preview to the user. On their approval, "
            "call confirm_reply with the same token. Token expires in 5 min."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["post", "note"], "default": "post"},
                "post_id": {"type": "string"},
                "note_id": {"type": "string"},
                "parent_comment_id": {"type": "string"},
                "body": {"type": "string"},
                "pub": {"type": "string"},
            },
            "required": ["body"],
        },
    },
    "confirm_reply": {
        "description": (
            "Post a previously-proposed reply by token. Idempotent via dedup DB. "
            "Returns the live Substack response (or {deduped: true} if already posted)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "token": {"type": "string"},
                "force": {"type": "boolean", "default": False},
            },
            "required": ["token"],
        },
    },
}


def list_tool_names() -> list[str]:
    return list(TOOLS.keys())


def _dispatch(name: str, args: dict[str, Any]) -> Any:
    """Dispatch one tool call to the underlying client/audit/dedup."""
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
