"""MCP stdio server for substack-ops.

20 tools wired to SubstackClient. The server uses the official `mcp` Python
SDK if available, otherwise raises a clear install message.

Tools:
  reads:    test_connection, get_own_profile, get_profile, list_posts, get_post,
            get_post_by_id, get_post_content, search_posts, list_notes,
            list_comments, get_feed
  writes:   publish_note, reply_to_note, comment_on_post, react_to_post,
            react_to_comment, restack_post, restack_note, delete_comment
  unique:   bulk_draft_replies, send_approved_drafts, audit_search, dedup_status
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

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
