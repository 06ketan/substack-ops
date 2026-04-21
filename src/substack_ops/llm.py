"""LLM wrapper for the daemon path. Subprocess-only.

For interactive use, prefer the MCP-native flow:
  get_unanswered_comments -> propose_reply -> confirm_reply
which lets your IDE / desktop LLM do the drafting with no API key at all.

For unattended `auto daemon` runs, this shells out to a host CLI
(claude / cursor-agent / codex) so you still pay $0 in API fees.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_SYSTEM = (
    "You are the author of a Substack newsletter replying to a reader's comment. "
    "Write a single, warm, personal reply (1-3 sentences). No emojis unless the "
    "reader used one. Don't restate their comment. Don't sign off. Plain text only."
)


@dataclass
class LLM:
    provider: str  # "subprocess" | "none"
    model: str
    api_key: str | None  # always None; kept for backward-compat dataclass shape

    @classmethod
    def from_env(cls, model: str | None = None) -> LLM:
        from substack_ops import llm_subprocess

        if llm_subprocess.is_available():
            return cls(
                provider="subprocess",
                model=llm_subprocess.detect_name() or "host-cli",
                api_key=None,
            )
        return cls(provider="none", model="", api_key=None)

    def draft(self, *, comment_body: str, comment_author: str, post_title: str | None = None) -> str:
        if self.provider == "subprocess":
            from substack_ops import llm_subprocess

            return llm_subprocess.draft(
                comment_body=comment_body,
                comment_author=comment_author,
                post_title=post_title,
            )
        raise RuntimeError(
            "No LLM available. Either:\n"
            "  - install a host CLI (claude code / cursor-agent / codex) on PATH, or\n"
            "  - set SUBSTACK_OPS_LLM_CMD='your-cli {prompt}', or\n"
            "  - use --template mode (no LLM), or\n"
            "  - use the MCP propose_reply / confirm_reply tools from your chat app."
        )
