"""Subprocess LLM provider — shells out to a host CLI for the daemon path.

Lets the unattended auto-daemon use your existing AI subscription (claude code,
cursor-agent, codex) instead of a paid Anthropic/OpenAI API key.

Resolution order (first hit wins):
  1. SUBSTACK_OPS_LLM_CMD env var (full command template, "{prompt}" placeholder
     optional — prompt is otherwise piped on stdin).
  2. `claude` on PATH      -> claude --print --append-system "<sys>"
  3. `cursor-agent` on PATH -> cursor-agent --print
  4. `codex` on PATH        -> codex --quiet
  5. raise SubprocessLLMNotFound
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass

DEFAULT_SYSTEM = (
    "You are the author of a Substack newsletter replying to a reader's comment. "
    "Write a single, warm, personal reply (1-3 sentences). No emojis unless the "
    "reader used one. Don't restate their comment. Don't sign off. Plain text only."
)

DEFAULT_TIMEOUT = 60


class SubprocessLLMNotFound(RuntimeError):
    pass


@dataclass
class _Recipe:
    name: str
    cmd: list[str]
    pass_via: str  # "stdin" | "arg"


def _detect() -> _Recipe:
    custom = os.environ.get("SUBSTACK_OPS_LLM_CMD")
    if custom:
        parts = shlex.split(custom)
        pass_via = "arg" if "{prompt}" in custom else "stdin"
        return _Recipe(name=parts[0], cmd=parts, pass_via=pass_via)

    if shutil.which("claude"):
        return _Recipe(
            name="claude",
            cmd=["claude", "--print", "--append-system-prompt", DEFAULT_SYSTEM],
            pass_via="stdin",
        )
    if shutil.which("cursor-agent"):
        return _Recipe(
            name="cursor-agent",
            cmd=["cursor-agent", "--print"],
            pass_via="stdin",
        )
    if shutil.which("codex"):
        return _Recipe(name="codex", cmd=["codex", "exec", "--quiet"], pass_via="stdin")

    raise SubprocessLLMNotFound(
        "No host LLM CLI found on PATH. Install one of: claude (claude code), "
        "cursor-agent, codex; or set SUBSTACK_OPS_LLM_CMD='your-cli {prompt}'."
    )


def is_available() -> bool:
    try:
        _detect()
        return True
    except SubprocessLLMNotFound:
        return False


def detect_name() -> str | None:
    try:
        return _detect().name
    except SubprocessLLMNotFound:
        return None


def draft(
    *,
    comment_body: str,
    comment_author: str,
    post_title: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    recipe = _detect()
    prompt = (
        f"Post title: {post_title or '(unknown)'}\n"
        f"Comment by {comment_author}:\n{comment_body.strip()}\n\n"
        "Write the reply now. Output ONLY the reply text, no preamble."
    )

    if recipe.pass_via == "arg":
        cmd = [p.replace("{prompt}", prompt) for p in recipe.cmd]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    else:
        full_prompt = f"SYSTEM: {DEFAULT_SYSTEM}\n\n{prompt}"
        result = subprocess.run(
            recipe.cmd,
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    if result.returncode != 0:
        raise RuntimeError(
            f"{recipe.name} exited {result.returncode}: {result.stderr.strip()[:500]}"
        )
    out = result.stdout.strip()
    if not out:
        raise RuntimeError(f"{recipe.name} returned empty output")
    return out
