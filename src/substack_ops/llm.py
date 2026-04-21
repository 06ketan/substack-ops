"""Provider-agnostic LLM wrapper for reply drafting.

Defaults: Anthropic (Claude) via ANTHROPIC_API_KEY.
Fallback:  OpenAI via OPENAI_API_KEY.
None:      raises if no key — caller can use template mode instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_SYSTEM = (
    "You are the author of a Substack newsletter replying to a reader's comment. "
    "Write a single, warm, personal reply (1-3 sentences). No emojis unless the "
    "reader used one. Don't restate their comment. Don't sign off. Plain text only."
)


@dataclass
class LLM:
    provider: str  # "anthropic" | "openai" | "none"
    model: str
    api_key: str | None

    @classmethod
    def from_env(cls, model: str | None = None) -> LLM:
        if os.environ.get("ANTHROPIC_API_KEY"):
            return cls(
                provider="anthropic",
                model=model or "claude-3-5-sonnet-20241022",
                api_key=os.environ["ANTHROPIC_API_KEY"],
            )
        if os.environ.get("OPENAI_API_KEY"):
            return cls(
                provider="openai",
                model=model or "gpt-4o-mini",
                api_key=os.environ["OPENAI_API_KEY"],
            )
        return cls(provider="none", model="", api_key=None)

    def draft(self, *, comment_body: str, comment_author: str, post_title: str | None = None) -> str:
        prompt = (
            f"Post title: {post_title or '(unknown)'}\n"
            f"Comment by {comment_author}:\n{comment_body.strip()}\n\n"
            "Write the reply now."
        )
        if self.provider == "anthropic":
            return self._anthropic(prompt)
        if self.provider == "openai":
            return self._openai(prompt)
        raise RuntimeError(
            "No LLM key set. Export ANTHROPIC_API_KEY or OPENAI_API_KEY, "
            "or use --template mode instead."
        )

    def _anthropic(self, prompt: str) -> str:
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "anthropic not installed. `uv add 'substack-ops[ai]'` or "
                "`uv pip install anthropic`."
            ) from e
        client = anthropic.Anthropic(api_key=self.api_key)
        msg = client.messages.create(
            model=self.model,
            max_tokens=300,
            system=DEFAULT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if hasattr(b, "text")).strip()

    def _openai(self, prompt: str) -> str:
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("openai not installed. `uv pip install openai`.") from e
        client = OpenAI(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": DEFAULT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
        )
        return (resp.choices[0].message.content or "").strip()
