# Substack-ops MCP prompt cheatsheet

After `substack-ops mcp install <host>` and a host restart, paste these into
your chat (Cursor, Claude Desktop, Claude Code) — the host LLM picks tools,
you stay in the driver's seat.

## 1. Daily comment triage

```
Use substack-ops to:
1. list my 10 most recent posts
2. for each, call get_unanswered_comments
3. show me a table: post_id | comment_id | author | snippet
```

## 2. Draft → preview → confirm (no API key)

```
For comment_id 12345 on post_id 193866852:
- read the comment (call list_comments)
- draft a warm 1-2 sentence reply in MY voice (you, the chat LLM, draft it)
- call propose_reply with that draft
- show me the preview, the dedup hash, and the token
- WAIT for me to say "yes" before calling confirm_reply
```

## 3. Bulk triage, my approval per item

```
get_unanswered_comments for post 193866852.
For each one:
- show me the comment body
- propose a reply
- ask "send / edit / skip?"
- on "send" call confirm_reply
- on "edit" let me rewrite, then propose_reply again
- on "skip" continue
Keep a running counter.
```

## 4. Restack a watchlist's latest note

```
For each handle in [@profgalloway, @arvindnarayanan, @benthompson]:
- get_profile to find their user_id
- list_notes for that user (latest 1)
- ask me yes/no
- on yes, restack_note
```

## 5. Audit what was sent

```
audit_search status=posted since=24h.
Group by mode (mcp:confirm_reply / ai_bulk:reply / template / ai_review).
Show counts.
```

## 6. Inspect dedup DB

```
dedup_status. Then audit_search status=deduped since=7d to see what got skipped.
```

## 7. Read-only research on someone else's pub

```
posts list --pub stratechery --limit 10
posts content <id> --md
posts search "ai" --pub stratechery
recommendations list --pub stratechery
```

## 8. Note thread and reply

```
list_notes (mine) — pick one.
list_comments on it.
For each top-level reply, propose_reply (kind=note) and let me approve.
```

## Style guardrails to put in the prompt

```
House style:
- Lowercase first letter unless proper noun
- 1-3 sentences max
- No emojis unless the commenter used one
- No "Great point!" / "Thanks for sharing!" openers
- Reference one specific thing they wrote
- End on a question only ~30% of the time
```
