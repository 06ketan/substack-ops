"""Auto-configure MCP hosts to launch substack-ops as a stdio server.

Hosts:
  cursor          ~/.cursor/mcp.json                              (JSON merge)
  claude-desktop  ~/Library/Application Support/Claude/...        (JSON merge,
                  %APPDATA%\\Claude\\..., ~/.config/Claude/...)
  claude-code     shells out to `claude mcp add --transport stdio ...`
  print           prints the JSON snippet only (manual install)

Always idempotent. Existing config is backed up to <file>.bak before write.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LINE_COMMENT_RE = re.compile(r"(?m)^\s*//.*$")
_INLINE_COMMENT_RE = re.compile(r"(?<!:)//[^\n]*")
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _loads_jsonc(text: str) -> Any:
    """Parse JSON tolerating // line comments and trailing commas (Cursor's mcp.json style)."""
    if not text.strip():
        return {}
    cleaned = _LINE_COMMENT_RE.sub("", text)
    cleaned = _INLINE_COMMENT_RE.sub("", cleaned)
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", cleaned)
    return json.loads(cleaned)

SERVER_BIN = "substack-ops"


def _server_block(name: str = "substack-ops") -> dict[str, Any]:
    bin_path = shutil.which(SERVER_BIN) or SERVER_BIN
    return {
        "command": bin_path,
        "args": ["mcp", "serve"],
        "env": {},
    }


def _cursor_config_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def _claude_desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = path.with_suffix(path.suffix + f".bak.{stamp}")
    shutil.copy2(path, bak)
    return bak


def _merge_json_config(path: Path, name: str, dry_run: bool) -> dict[str, Any]:
    block = _server_block(name)
    snippet = {"mcpServers": {name: block}}

    if path.exists():
        try:
            data = _loads_jsonc(path.read_text())
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"refusing to overwrite invalid JSON at {path}: {exc}") from exc
    else:
        data = {}

    servers = data.setdefault("mcpServers", {})
    already = servers.get(name) == block
    servers[name] = block

    if dry_run:
        return {
            "host_config": str(path),
            "would_write": True,
            "already_present": already,
            "snippet": json.dumps(snippet, indent=2),
        }

    bak = _backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return {
        "host_config": str(path),
        "wrote": True,
        "backup": str(bak) if bak else None,
        "already_present": already,
        "server_name": name,
        "command": block["command"],
        "args": " ".join(block["args"]),
    }


def _claude_code_install(name: str, dry_run: bool) -> dict[str, Any]:
    if not shutil.which("claude"):
        raise RuntimeError(
            "`claude` CLI not on PATH. Install Claude Code from "
            "https://docs.claude.com/en/docs/claude-code, then re-run."
        )
    bin_path = shutil.which(SERVER_BIN) or SERVER_BIN
    cmd = [
        "claude", "mcp", "add",
        "--transport", "stdio",
        "--scope", "user",
        name, "--", bin_path, "mcp", "serve",
    ]
    if dry_run:
        return {"would_run": " ".join(cmd)}

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return {
        "ran": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def _print_snippet(name: str) -> dict[str, Any]:
    snippet = {"mcpServers": {name: _server_block(name)}}
    return {
        "snippet": json.dumps(snippet, indent=2),
        "next_steps": (
            "Paste this into your host's MCP config and restart the host. "
            "Cursor: ~/.cursor/mcp.json. "
            "Claude Desktop: Settings → Developer → Edit Config."
        ),
    }


def install_to_host(*, host: str, name: str = "substack-ops", dry_run: bool = False) -> dict[str, Any]:
    host_norm = host.strip().lower()
    if host_norm in ("cursor",):
        return _merge_json_config(_cursor_config_path(), name, dry_run)
    if host_norm in ("claude-desktop", "claude_desktop", "claudedesktop"):
        return _merge_json_config(_claude_desktop_config_path(), name, dry_run)
    if host_norm in ("claude-code", "claude_code", "claudecode"):
        return _claude_code_install(name, dry_run)
    if host_norm in ("print", "snippet"):
        return _print_snippet(name)
    raise ValueError(
        f"unknown host: {host}. choose: cursor | claude-desktop | claude-code | print"
    )
