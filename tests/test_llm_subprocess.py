"""Subprocess LLM provider — detection and shell-out shape (no real CLI calls)."""

from __future__ import annotations

import subprocess

import pytest

from substack_ops import llm_subprocess
from substack_ops.llm import LLM


def test_custom_env_var_takes_priority(monkeypatch):
    monkeypatch.setenv("SUBSTACK_OPS_LLM_CMD", "myllm --print")
    recipe = llm_subprocess._detect()
    assert recipe.name == "myllm"
    assert recipe.cmd == ["myllm", "--print"]
    assert recipe.pass_via == "stdin"


def test_custom_env_var_with_prompt_placeholder(monkeypatch):
    monkeypatch.setenv("SUBSTACK_OPS_LLM_CMD", "myllm --prompt {prompt}")
    recipe = llm_subprocess._detect()
    assert recipe.pass_via == "arg"


def test_no_cli_no_env_raises(monkeypatch):
    monkeypatch.delenv("SUBSTACK_OPS_LLM_CMD", raising=False)
    monkeypatch.setattr(llm_subprocess.shutil, "which", lambda _: None)
    with pytest.raises(llm_subprocess.SubprocessLLMNotFound):
        llm_subprocess._detect()


def test_is_available_false(monkeypatch):
    monkeypatch.delenv("SUBSTACK_OPS_LLM_CMD", raising=False)
    monkeypatch.setattr(llm_subprocess.shutil, "which", lambda _: None)
    assert llm_subprocess.is_available() is False
    assert llm_subprocess.detect_name() is None


def test_claude_detected_when_on_path(monkeypatch):
    monkeypatch.delenv("SUBSTACK_OPS_LLM_CMD", raising=False)
    monkeypatch.setattr(
        llm_subprocess.shutil,
        "which",
        lambda name: "/usr/local/bin/claude" if name == "claude" else None,
    )
    recipe = llm_subprocess._detect()
    assert recipe.name == "claude"
    assert "--print" in recipe.cmd


def test_cursor_agent_detected_when_no_claude(monkeypatch):
    monkeypatch.delenv("SUBSTACK_OPS_LLM_CMD", raising=False)
    monkeypatch.setattr(
        llm_subprocess.shutil,
        "which",
        lambda name: "/usr/local/bin/cursor-agent" if name == "cursor-agent" else None,
    )
    recipe = llm_subprocess._detect()
    assert recipe.name == "cursor-agent"


def test_draft_pipes_prompt_via_stdin(monkeypatch):
    monkeypatch.setenv("SUBSTACK_OPS_LLM_CMD", "fake-cli")
    captured: dict = {}

    def _fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["input"] = kw.get("input")
        return subprocess.CompletedProcess(cmd, 0, stdout="hello reply\n", stderr="")

    monkeypatch.setattr(llm_subprocess.subprocess, "run", _fake_run)
    out = llm_subprocess.draft(
        comment_body="thanks for writing",
        comment_author="alice",
        post_title="my post",
    )
    assert out == "hello reply"
    assert captured["cmd"] == ["fake-cli"]
    assert "alice" in captured["input"]
    assert "my post" in captured["input"]


def test_draft_substitutes_prompt_arg(monkeypatch):
    monkeypatch.setenv("SUBSTACK_OPS_LLM_CMD", "fake-cli --prompt {prompt}")
    captured: dict = {}

    def _fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["input"] = kw.get("input")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(llm_subprocess.subprocess, "run", _fake_run)
    llm_subprocess.draft(comment_body="x", comment_author="bob")
    assert captured["input"] is None
    assert captured["cmd"][0] == "fake-cli"
    assert any("bob" in p for p in captured["cmd"])


def test_draft_nonzero_exit_raises(monkeypatch):
    monkeypatch.setenv("SUBSTACK_OPS_LLM_CMD", "fake-cli")
    monkeypatch.setattr(
        llm_subprocess.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(["fake-cli"], 7, stdout="", stderr="boom"),
    )
    with pytest.raises(RuntimeError, match="exited 7"):
        llm_subprocess.draft(comment_body="x", comment_author="y")


def test_draft_empty_output_raises(monkeypatch):
    monkeypatch.setenv("SUBSTACK_OPS_LLM_CMD", "fake-cli")
    monkeypatch.setattr(
        llm_subprocess.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(["fake-cli"], 0, stdout="   ", stderr=""),
    )
    with pytest.raises(RuntimeError, match="empty output"):
        llm_subprocess.draft(comment_body="x", comment_author="y")


def test_llm_from_env_returns_subprocess_when_cli_available(monkeypatch):
    monkeypatch.setenv("SUBSTACK_OPS_LLM_CMD", "fake-cli")
    llm = LLM.from_env()
    assert llm.provider == "subprocess"
    assert llm.api_key is None
    assert llm.model == "fake-cli"


def test_llm_from_env_returns_none_when_nothing_available(monkeypatch):
    monkeypatch.delenv("SUBSTACK_OPS_LLM_CMD", raising=False)
    monkeypatch.setattr(llm_subprocess.shutil, "which", lambda _: None)
    llm = LLM.from_env()
    assert llm.provider == "none"


def test_llm_draft_raises_clear_error_when_no_provider(monkeypatch):
    monkeypatch.delenv("SUBSTACK_OPS_LLM_CMD", raising=False)
    monkeypatch.setattr(llm_subprocess.shutil, "which", lambda _: None)
    llm = LLM.from_env()
    with pytest.raises(RuntimeError, match="No LLM available"):
        llm.draft(comment_body="x", comment_author="y")
