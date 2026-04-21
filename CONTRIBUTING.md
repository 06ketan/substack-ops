# Contributing to substack-ops

Thanks for picking this up. `substack-ops` is intentionally small, so contributions land fast when they're scoped tight.

## Ground rules

- **One change per PR.** A bug fix, a tool, a doc pass — not all three.
- **Dry-run is sacred.** Anything that talks to Substack must default to `dry_run=True` and emit an audit row.
- **Tool descriptions are first-class.** When you add or edit an MCP tool, the description has to spell out side effects, the exact ID it expects, and the sibling tool a caller might confuse it with. We optimize for [Glama TDQS](https://glama.ai/mcp/servers).
- **No new runtime dependencies** without a strong reason. The point is `pip install substack-ops` ships in seconds.

## Dev setup

```bash
git clone https://github.com/06ketan/substack-ops.git
cd substack-ops
uv sync --all-extras
cp .env.example .env  # fill in SUBSTACK_SESSION
uv run substack-ops auth test
```

## Running

```bash
uv run substack-ops --help            # CLI surface
uv run substack-ops mcp serve         # MCP server (stdio)
uv run pytest -q                      # tests
uv run ruff check .                   # lint
uv run mypy src/substack_ops          # types
```

## Layout

```
src/substack_ops/
  cli.py           # CLI entrypoints (Typer)
  client.py        # Substack HTTP client
  mcp/server.py    # MCP server + 26 tools
  mcp/install.py   # auto-install into Cursor / Claude / Codex
  audit.py         # JSONL audit log
  dedup.py         # SQLite dedup store
  daemon/          # background runner + TUI
```

## Adding an MCP tool

1. Implement the function in the relevant module under `src/substack_ops/`.
2. Register it in `src/substack_ops/mcp/server.py` `TOOLS` dict with:
   - **`description`** — start with the side-effect tag (`Read-only.` / `Write.` / `STAGE A WRITE` / `DESTRUCTIVE.`), say what it returns, name the sibling tool to use instead.
   - **`input_schema`** — every property gets a `description`.
3. Add a unit test in `tests/`.
4. If it mutates Substack: route through `audit.log_event()` and `dedup.check()`.

## Reporting bugs

Open an [issue](https://github.com/06ketan/substack-ops/issues/new) with:
- `substack-ops --version`
- Python version (`python -V`)
- The exact command + stack trace
- Whether `auth test` succeeds

## Releasing (maintainers)

1. Bump `version` in `pyproject.toml`, `server.json`, and `src/substack_ops/__init__.py`.
2. `git tag -a vX.Y.Z -m "release: vX.Y.Z"`.
3. `git push --tags` — the publish workflow does the rest (PyPI + GitHub release).

## License

By contributing, you agree your code is released under the [MIT License](LICENSE).
