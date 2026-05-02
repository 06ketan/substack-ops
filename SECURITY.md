# Security Policy

## Supported Versions

Only the **latest minor** of `substack-ops` on PyPI is supported. Older versions
do not receive security backports.

| Version | Supported          |
| ------- | ------------------ |
| 0.3.x   | :white_check_mark: |
| < 0.3   | :x:                |

## Reporting a Vulnerability

**Do not open a public GitHub Issue for security reports.**

If you believe you've found a security issue, please email:

- **ketan.chavan.test@gmail.com**

Include:

- A clear description of the vulnerability
- Steps to reproduce (or a proof-of-concept if applicable)
- The version of `substack-ops` you tested against
- Your assessment of the impact and severity

You should expect an acknowledgement within **72 hours**. Coordinated disclosure
windows are negotiable; the default is **30 days** before public details are
published.

## Auth Token Handling — User Expectations

`substack-ops` reads three credentials that grant write access to your Substack
account:

- `SUBSTACK_PUBLICATION_URL`
- `SUBSTACK_USER_ID`
- `SUBSTACK_SESSION_TOKEN` (treat this as a password — it is the value of the
  `substack.sid` cookie on substack.com)

### What you must never do

- **Never paste `SUBSTACK_SESSION_TOKEN` into a public GitHub Issue, blog post,
  Slack channel, screenshot, or LLM prompt.** A leaked token gives full write
  access to your account until you rotate it.
- **Never commit `mcp.json` or `.env` files containing the token to a public
  repository.** Both are listed in `.gitignore`; do not remove them.
- **Never share your token across machines.** Substack invalidates the cookie
  if it sees the same token on dramatically different IPs.

### What this tool does to protect you

- The MCP server only reads the token from environment / `~/.cursor/mcp.json`
  / `auth login` keyring — it is **never** logged.
- All write tools default to `dry_run=true`. You must explicitly opt in to a
  real write.
- The `propose_reply` / `confirm_reply` two-step flow means the MCP host has to
  surface the exact body to you before any network call is made.
- Local `dedup.db` and `audit.jsonl` track every successful (or attempted)
  write so you can audit the tool's behavior.

### How to rotate a leaked token

1. Sign out of substack.com on every device (`Settings → Account → Sign out
   everywhere`).
2. Sign back in once on the device you trust.
3. Re-run `substack-ops auth login --browser chrome` to grab the new cookie.

## Hardening Recommendations

- Run the MCP server only inside the IDE you trust (Cursor / Claude Desktop).
- Do not expose the MCP server over the network — it is `stdio`-only by design.
- Pin to a specific `substack-ops` version in your `mcp.json` if you want to
  audit changes between versions; use `uvx substack-ops@0.3.3 mcp serve`.
