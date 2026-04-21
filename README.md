# substack-ops

Standalone Python toolkit for everything you can do on Substack from a terminal:
posts, notes, comments, replies, reactions, restacks, recommendations, search,
profiles, feeds, automations, an MCP server, and a Textual TUI.

**No runtime dependency on `NHagar/substack_api` or `postcli/substack`.** All
needed upstream code is vendored and ported to `httpx` under
`src/substack_ops/_substack/`. AGPL-clean: we re-implement against the same
documented endpoints; we do not copy AGPL-licensed code from postcli.

## Setup

```bash
cd substack-ops
uv sync
uv sync --extra ai      # anthropic + openai for AI reply modes
uv sync --extra tui     # textual for the TUI
uv sync --extra mcp     # mcp SDK for the MCP server
uv sync --extra chrome  # pycryptodome + keyring for Chrome cookie auto-grab
```

Auth defaults to `~/.cursor/mcp.json`'s `mcpServers.substack-api.env`. Override
with env or `.env`. Or use one of the 3 new auth flows in `auth login` /
`auth setup`.

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
substack-ops mcp --list-tools     # 23 tools
substack-ops mcp                   # stdio server
```

Cursor / Claude Desktop config:

```json
{
  "mcpServers": {
    "substack-ops": {
      "command": "uv",
      "args": ["--directory", "/abs/path/to/substack-ops", "run", "substack-ops", "mcp"]
    }
  }
}
```

If the `mcp` SDK is not installed, the server falls back to a minimal
`stdin/stdout` JSON-line dispatcher that's still useful for scripting and
tests:

```bash
echo '{"tool":"list_posts","args":{"limit":3}}' | substack-ops mcp
```

The 4 tools that are unique to substack-ops (not in postcli):
`bulk_draft_replies`, `send_approved_drafts`, `audit_search`, `dedup_status`.

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
