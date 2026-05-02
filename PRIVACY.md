# Privacy Policy — substack-ops

**Last updated:** May 2, 2026

## Overview

`substack-ops` is a local Python CLI + MCP server that talks to your own
Substack account on your behalf. It runs entirely on your machine. There is
**no `substack-ops` server**, **no telemetry**, and **no analytics**.

## Data Collection

`substack-ops` does **not** collect, transmit, or store any user data on
remote servers operated by the project. All processing happens locally on
your device.

## Data Flow

When you run a tool, two parties may receive data:

1. **substack.com** — when a tool calls Substack's API to read posts/comments
   or post a reply, request data goes to substack.com. This is governed by
   [Substack's privacy policy](https://substack.com/privacy). `substack-ops`
   acts on your behalf using **your** session cookie.
2. **The MCP host you run** — when you use the MCP server inside Cursor /
   Claude Desktop / Claude Code / a similar IDE, the IDE's LLM sees the tool
   inputs and outputs you choose to share with it. Refer to your IDE's
   privacy policy for how that data is handled.

`substack-ops` itself adds **no** third party.

## Local Data Retention

The tool writes the following local files (configurable):

- `audit.jsonl` — append-only log of every write tool call (kind, target id,
  body hash, timestamp, dry-run flag, response status). Stored in the working
  directory or `SUBSTACK_OPS_HOME`.
- `dedup.db` — SQLite database keyed by content hash. Used to make repeated
  writes idempotent. Contains the body hash, the tool name, and the timestamp.
  **Does not** contain the body itself.
- Optional reply drafts (`note-drafts*.json`) when you use `bulk_draft_replies`.

Delete these files at any time to wipe local history. The tool does not back
them up anywhere.

## Credentials

- `SUBSTACK_SESSION_TOKEN` is read from environment, `~/.cursor/mcp.json`, or
  the OS keyring (when set up via `auth login`). It is **never** logged and
  **never** written to `audit.jsonl` or `dedup.db`.
- Other env vars (`SUBSTACK_PUBLICATION_URL`, `SUBSTACK_USER_ID`) are not
  considered secret but are still not transmitted anywhere except substack.com.

## Network Activity

- The MCP server starts no HTTP server and opens no listening ports.
- Communication with the MCP host is **stdio only**.
- HTTPS calls go only to `substack.com`, your publication's substack subdomain,
  and (for cookie auto-grab) your local browser's profile directory.

## Children's Privacy

This tool does not knowingly collect any information from anyone, including
children under 13.

## Changes to This Policy

Material changes will be committed to this file. The git history is the
authoritative changelog.

## Contact

For privacy questions or concerns:

- **GitHub Issues** (non-sensitive): [github.com/06ketan/substack-ops/issues](https://github.com/06ketan/substack-ops/issues)
- **Email** (sensitive / security-adjacent): ketan.chavan.test@gmail.com
- **Author**: Ketan Chavan
