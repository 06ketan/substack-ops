# substack-ops

[![PyPI version](https://img.shields.io/pypi/v/substack-ops?color=ff6719&label=pypi)](https://pypi.org/project/substack-ops/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP compatible](https://img.shields.io/badge/MCP-compatible-8A2BE2)](https://modelcontextprotocol.io)
[![CI](https://github.com/06ketan/substack-ops/actions/workflows/test.yml/badge.svg)](https://github.com/06ketan/substack-ops/actions/workflows/test.yml)

> **Standalone Substack CLI + 26-tool MCP server. Your IDE drafts the replies. Zero AI API keys.**

Site → **[substack-ops.chavan.in](https://substack-ops.chavan.in)** · Source → **[06ketan/substack-ops](https://github.com/06ketan/substack-ops)**

Posts, notes, comments, replies, reactions, restacks, recommendations, search,
profiles, feeds, automations, MCP server, Textual TUI.

**No runtime dependency on `NHagar/substack_api` or `postcli/substack`.** All
upstream code is vendored and ported to `httpx` under
`src/substack_ops/_substack/`. AGPL-clean: we re-implement against the same
documented endpoints; we do not copy AGPL-licensed code from postcli.

## TL;DR — MCP-native (no API key, one command)

```bash
uvx substack-ops mcp install cursor          # or claude-desktop, claude-code, print
# Restart your host. Then in chat:
#   "list unanswered comments on post 193866852"
#   "draft a warm reply to comment 12345"
#   "post that draft"
```

Your **host's** LLM (Cursor's, Claude's) does the drafting via the
`propose_reply` / `confirm_reply` tools. No `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` needed.

## Setup (dev / from source)

```bash
git clone https://github.com/06ketan/substack-ops && cd substack-ops
uv sync
uv sync --extra mcp     # mcp SDK for the MCP server (recommended)
uv sync --extra tui     # textual for the TUI
uv sync --extra chrome  # pycryptodome + keyring for Chrome cookie auto-grab
```

Auth defaults to `~/.cursor/mcp.json`'s `mcpServers.substack-api.env`. Override
with env or `.env`. Or use one of the auth flows in `auth login` / `auth setup`.

```bash
uv run substack-ops auth verify
uv run substack-ops quickstart   # 20-step tour
```

## Command surface

```text
substack-ops auth verify | test | login [--browser chrome|brave] [--email <addr>] | setup
substack-ops posts list | show <id|slug> | stats <id> | content <id> [--md]
                | search <query> [--pub] | paywalled <id> | get --slug <slug>
                | react <id> [--off] | restack <id> [--off]
substack-ops notes list | show <id> | publish <body>
                | react <id> [--off] | restack <id> [--off]
substack-ops comments tree <post_id> | export <post_id> --out <f>
                | add <post_id> <body> | react <id> --kind post|note
                | delete <id> --kind post|note
substack-ops reply template <post_id> --template <name>
              | review <post_id>
              | bulk <post_id> --out drafts.json
              | note-bulk <note_id> --out drafts.json
              | bulk-send drafts.json [--no-dry-run]
              | auto <post_id> --no-dry-run --yes-i-mean-it
substack-ops podcasts list [--pub]
substack-ops recommendations list [--pub]
substack-ops authors list [--pub]
substack-ops categories list | get --name X
substack-ops users get <handle> | subscriptions <handle>
substack-ops profile me | get <handle>
substack-ops feed list --tab for-you|subscribed|category-{slug}
substack-ops audit search [--kind] [--target] [--status] [--since 7d]
              | dedup-status
substack-ops auto presets | run <name> | daemon <name> --interval 60
substack-ops mcp [--list-tools]
substack-ops tui
substack-ops quickstart
```

Every write op defaults to `--dry-run` and is logged to `.cache/audit.jsonl`.
Live writes are checked against `.cache/actions.db` (SQLite dedup) and refused
if duplicate, unless `--force`.

## Multi-publication

Every read command accepts `--pub <subdomain|domain>`. Defaults to your own
publication.

```bash
substack-ops posts list --pub stratechery --limit 5
substack-ops posts search "ai" --pub stratechery
substack-ops recommendations list --pub stratechery
```

## Reply modes

| Mode | What it does | Safety |
|------|--------------|--------|
| `template` | YAML keyword/regex rules under `src/substack_ops/templates/*.yaml` | dry-run default |
| `review` | LLM drafts each reply, you `[a]ccept / [e]dit / [s]kip / [q]uit` | dry-run default + manual gate per comment |
| `bulk` | LLM drafts every comment to `drafts.json`. Edit file, set `action: "approved"` | offline review, dedup-checked on send |
| `bulk-send` | Posts only items with `action: "approved"` | dry-run default; **dedup DB prevents the M2 31-dup-replies regression** |
| `auto` | LLM drafts and posts immediately | requires `--no-dry-run --yes-i-mean-it`, 30s rate limit |

After every live note-reply the engine re-fetches the new comment and asserts
`ancestor_path` is non-empty. If empty, the audit row's `result_status` is
flipped to `"orphaned"` (the M2 bug where `parent_comment_id` was silently
dropped — now caught).

## Automations

Built-in presets (`auto presets`):

1. **like-back** — when someone reacts to your note, react to their latest note.
2. **auto-reply** — same trigger, but post a templated thank-you.
3. **auto-restack** — when a watchlist handle posts a new note, restack it.
4. **follow-back** — when someone follows you, follow them back.

Custom YAML rules under `~/.config/substack-ops/auto/*.yaml`. Loop with
`auto daemon <name> --interval 60`.

## MCP server

```bash
substack-ops mcp install cursor              # auto-add to ~/.cursor/mcp.json
substack-ops mcp install claude-desktop      # auto-add to claude_desktop_config.json
substack-ops mcp install claude-code         # uses `claude mcp add` under the hood
substack-ops mcp install print               # print the snippet only
substack-ops mcp install cursor --dry-run    # preview without writing
substack-ops mcp serve                       # stdio server
substack-ops mcp list-tools                  # 26 tools
```

Manual config snippet (if you prefer):

```json
{
  "mcpServers": {
    "substack-ops": {
      "command": "substack-ops",
      "args": ["mcp", "serve"]
    }
  }
}
```

If the `mcp` SDK is not installed, the server falls back to a minimal
`stdin/stdout` JSON-line dispatcher that's still useful for scripting:

```bash
echo '{"tool":"list_posts","args":{"limit":3}}' | substack-ops mcp serve
```

### MCP-native draft loop (no API key)

3 tools designed to let your **host** LLM draft for you:

| Tool | What it does |
|------|--------------|
| `get_unanswered_comments` | Returns the worklist: comments where you have not yet replied (any depth). |
| `propose_reply` | Dry-run only. Returns a `token` + payload preview. **No write.** |
| `confirm_reply` | Posts a previously-proposed reply by token. Idempotent via dedup DB. Token TTL 5 min. |

Tools unique to substack-ops (not in postcli/NHagar):
`bulk_draft_replies`, `send_approved_drafts`, `audit_search`, `dedup_status`,
`get_unanswered_comments`, `propose_reply`, `confirm_reply`.

## LLM strategy

Two layers, both free:

1. **MCP-native (default).** Host LLM drafts via `propose_reply` /
   `confirm_reply`. No env vars, no API key. Use this for interactive replies.
2. **Subprocess CLI (daemon path).** For `reply auto` / `auto daemon` when
   no human is in the loop. Auto-detects `claude` (Claude Code),
   `cursor-agent`, or `codex` on PATH. Override with `SUBSTACK_OPS_LLM_CMD`.

There is no paid-API-key path. If you want one, vendor the old `_anthropic` /
`_openai` methods from `substack-ops` v0.2.0 yourself.

## Textual TUI

```bash
substack-ops tui
```

6 tabs: Notes / Posts / Comments / Feed / Auto / Profile.
Sub-tabs: 1=mine, 2=following, 3=general.
Keys: tab, 1-3, ↑/↓, enter, r, l, s, o, q/esc.

## Auth methods

```bash
substack-ops auth verify                  # uses mcp.json or env
substack-ops auth login                   # auto-grab cookies from Chrome (macOS Keychain)
substack-ops auth login --browser brave
substack-ops auth login --email me@x.com  # email magic-link, paste-the-link mode
substack-ops auth setup                   # interactive paste cookies
```

## Architecture

```text
mcp.json | env | Chrome | OTP  →  auth.py / auth_chrome.py / auth_otp.py
                                            │
                                  .cache/cookies.json
                                            │
                                  SubstackClient (httpx)
                                            │
   ┌──────┬──────┬───────┬───────┬───────┬──────┬──────┬─────┬──────┐
   ▼      ▼      ▼       ▼       ▼       ▼      ▼      ▼     ▼      ▼
 posts  notes  comments  feed  profile  users  recs  cats  ...   reply_engine
                                                                       │
                                                       ┌───────────────┼────────────┐
                                                       ▼               ▼            ▼
                                                  template       ai_review     ai_bulk + ai_auto
                                                       └───────────────┬────────────┘
                                                                       ▼
                                                            base.post_reply / post_note_reply
                                                                       │
                                                              ┌────────┼────────┐
                                                              ▼        ▼        ▼
                                                            dedup    audit  ancestor_path
                                                            (SQLite) (jsonl)  guardrail
   auto/engine.py ────────────────┐
   mcp/server.py  ──── 23 tools ──┼─── all share SubstackClient
   tui/app.py     ──── 6 tabs   ──┘
```

## Endpoints used

| Action | Method + URL |
|--------|--------------|
| Auth check | `GET https://substack.com/api/v1/subscriptions` |
| List posts | `GET {pub}/api/v1/archive` |
| Post by id | `GET {pub}/api/v1/posts/by-id/{id}` |
| Post by slug | `GET {pub}/api/v1/posts/{slug}` |
| Post content | same as above; `body_html` field |
| Post search | `GET {pub}/api/v1/archive?search=` |
| Comments | `GET {pub}/api/v1/post/{id}/comments?all_comments=true` |
| Reply to comment | `POST {pub}/api/v1/post/{id}/comment` body `{body, parent_id}` |
| Add top-level comment | same with `parent_id: null` |
| React to post | `POST {pub}/api/v1/post/{id}/reaction` body `{reaction}` |
| Restack post | `POST https://substack.com/api/v1/restack` body `{post_id}` |
| Restack note | `POST https://substack.com/api/v1/restack` body `{comment_id}` |
| Delete post-comment | `DELETE {pub}/api/v1/comment/{id}` (PUB host) |
| Delete note | `DELETE https://substack.com/api/v1/comment/{id}` (BARE host) |
| My notes | `GET https://substack.com/api/v1/reader/feed/profile/{user_id}` |
| Note thread | `GET https://substack.com/api/v1/reader/comment/{note_id}` |
| Note replies | `GET https://substack.com/api/v1/reader/comment/{note_id}/replies` |
| Publish note | `POST https://substack.com/api/v1/comment/feed` body `{bodyJson}` |
| Reply to note | same with `{bodyJson, parent_id}` (NOT `parent_comment_id` — known M2 bug) |
| React to comment | `POST {host}/api/v1/comment/{id}/reaction` (host = pub for post-comments, substack.com for notes) |
| Recommendations | `GET {pub}/api/v1/recommendations/from/{publication_id}` |
| Authors | `GET {pub}/api/v1/publication/users/ranked?public=true` |
| Categories | `GET https://substack.com/api/v1/categories` |
| User profile | `GET https://substack.com/api/v1/user/{handle}/public_profile` (auto-redirects on 404) |
| Reader feed | `GET https://substack.com/api/v1/reader/feed/{recommended\|subscribed\|category/{slug}}` |

## Tests

```bash
uv run pytest -q     # 43 tests, ~0.6s, no live network
```

Coverage today: auth, client (read+write+engagement+delete), reply engine,
dedup DB, audit log search, MCP tool registry & dispatcher, automation engine
preset loader, the M2 `parent_id` regression test, the M2 host-mismatch
regression test.

## GSD workflow

`.planning/` scaffold for [Get Shit Done](https://github.com/khromov/get-shit-done)
under `~/.claude/skills/gsd-*`. Roadmap at `.planning/ROADMAP.md`,
per-phase plans at `.planning/phases/M*/PHASE.md`.

## Known gaps

- Full email stats (opens/clicks/views) — needs dashboard CSRF flow. Fallback: Playwright MCP scrape.
- Reactions endpoint shape on POST/DELETE not yet probed live; current shape is a best-guess from postcli's tool list.
- Auto-engine `new_follower` / `new_note_from` triggers are stubbed (return `note: "trigger not yet implemented"`).
- TUI sub-tabs (1/2/3) and reply/like/restack key bindings are scaffolded but not wired to the client yet.
- Chrome cookie auto-grab tested only for macOS Chrome; Brave path included; Linux/Windows not supported.

## License

MIT (this repo). Vendored upstream code is MIT-licensed per
`NHagar/substack_api`'s LICENSE. We do not include code from `postcli/substack`
(AGPL-3.0); we re-implement against the same documented endpoints.
