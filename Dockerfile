# Dockerfile for Glama introspection + standalone container deploys.
# Image entrypoint runs the MCP stdio server. Substack creds come from env
# (SUBSTACK_PUBLICATION_URL / SUBSTACK_USER_ID / SUBSTACK_SESSION_TOKEN) or
# from a mounted ~/.cursor/mcp.json (override path with SUBSTACK_OPS_MCP_PATH).

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# uv for fast deterministic installs
COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /usr/local/bin/uv

# Manifest first for layer caching
COPY pyproject.toml uv.lock README.md LICENSE ./

# Source second
COPY src ./src

# Install with mcp extra; freeze versions to uv.lock
RUN uv sync --frozen --no-dev --extra mcp \
    && uv build --wheel \
    && uv pip install --system dist/*.whl

# Runtime stage — small final image
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=base /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=base /usr/local/bin/substack-ops /usr/local/bin/substack-ops

# Non-root for safety
RUN useradd --uid 10001 --user-group --create-home --home-dir /home/app app
USER app

# stdio MCP server
ENTRYPOINT ["substack-ops", "mcp", "serve"]
