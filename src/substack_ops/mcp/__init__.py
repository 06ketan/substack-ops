"""substack-ops MCP server (stdio).

Exposes 26 tools for Cursor / Claude Desktop / Claude Code / any MCP host:
read posts, notes, comments, profiles, feeds; write replies, reactions,
restacks; the propose_reply / confirm_reply pattern lets the host LLM draft
without an API key; bulk_draft_replies + send_approved_drafts + audit_search +
dedup_status form the safety stack for unattended runs.
"""
