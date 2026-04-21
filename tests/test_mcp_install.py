"""mcp install: JSON-merge into Cursor / Claude Desktop, snippet for manual."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from substack_ops.mcp import install as inst


def test_unknown_host_raises():
    with pytest.raises(ValueError, match="unknown host"):
        inst.install_to_host(host="vim", dry_run=True)


def test_print_returns_snippet_only():
    out = inst.install_to_host(host="print")
    assert "snippet" in out
    snippet = json.loads(out["snippet"])
    assert "mcpServers" in snippet
    assert "substack-ops" in snippet["mcpServers"]
    block = snippet["mcpServers"]["substack-ops"]
    assert block["args"] == ["mcp", "serve"]


def test_cursor_creates_new_config(tmp_path: Path, monkeypatch):
    cfg = tmp_path / ".cursor" / "mcp.json"
    monkeypatch.setattr(inst, "_cursor_config_path", lambda: cfg)
    out = inst.install_to_host(host="cursor")
    assert cfg.exists()
    data = json.loads(cfg.read_text())
    assert "substack-ops" in data["mcpServers"]
    assert out["already_present"] is False
    assert out["backup"] is None


def test_cursor_merges_with_existing_servers(tmp_path: Path, monkeypatch):
    cfg = tmp_path / ".cursor" / "mcp.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        json.dumps({"mcpServers": {"github": {"command": "gh-mcp", "args": []}}})
    )
    monkeypatch.setattr(inst, "_cursor_config_path", lambda: cfg)
    inst.install_to_host(host="cursor")
    data = json.loads(cfg.read_text())
    assert "github" in data["mcpServers"]
    assert "substack-ops" in data["mcpServers"]
    assert any(p.name.startswith("mcp.json.bak.") for p in cfg.parent.iterdir())


def test_cursor_idempotent(tmp_path: Path, monkeypatch):
    cfg = tmp_path / ".cursor" / "mcp.json"
    monkeypatch.setattr(inst, "_cursor_config_path", lambda: cfg)
    inst.install_to_host(host="cursor")
    out = inst.install_to_host(host="cursor")
    assert out["already_present"] is True


def test_dry_run_does_not_write(tmp_path: Path, monkeypatch):
    cfg = tmp_path / ".cursor" / "mcp.json"
    monkeypatch.setattr(inst, "_cursor_config_path", lambda: cfg)
    out = inst.install_to_host(host="cursor", dry_run=True)
    assert not cfg.exists()
    assert out["would_write"] is True
    assert "substack-ops" in out["snippet"]


def test_invalid_json_refuses_to_overwrite(tmp_path: Path, monkeypatch):
    cfg = tmp_path / ".cursor" / "mcp.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("this is not json {")
    monkeypatch.setattr(inst, "_cursor_config_path", lambda: cfg)
    with pytest.raises(RuntimeError, match="invalid JSON"):
        inst.install_to_host(host="cursor")


def test_claude_desktop_writes_to_resolved_path(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "Claude" / "claude_desktop_config.json"
    monkeypatch.setattr(inst, "_claude_desktop_config_path", lambda: cfg)
    inst.install_to_host(host="claude-desktop")
    data = json.loads(cfg.read_text())
    assert "substack-ops" in data["mcpServers"]


def test_claude_code_requires_claude_on_path(monkeypatch):
    monkeypatch.setattr(inst.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="claude.*CLI not on PATH"):
        inst.install_to_host(host="claude-code")


def test_claude_code_dry_run_returns_command(monkeypatch):
    monkeypatch.setattr(
        inst.shutil,
        "which",
        lambda name: "/usr/local/bin/claude" if name == "claude" else "/usr/local/bin/substack-ops",
    )
    out = inst.install_to_host(host="claude-code", dry_run=True)
    assert "would_run" in out
    assert "claude mcp add" in out["would_run"]
    assert "substack-ops" in out["would_run"]
    assert "stdio" in out["would_run"]


def test_claude_code_runs_subprocess(monkeypatch):
    monkeypatch.setattr(
        inst.shutil,
        "which",
        lambda name: "/usr/local/bin/claude" if name == "claude" else "/usr/local/bin/substack-ops",
    )
    captured: dict = {}

    def _fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="added", stderr="")

    monkeypatch.setattr(inst.subprocess, "run", _fake_run)
    out = inst.install_to_host(host="claude-code")
    assert out["returncode"] == 0
    assert "claude" in captured["cmd"][0]
    assert captured["cmd"][1:5] == ["mcp", "add", "--transport", "stdio"]
