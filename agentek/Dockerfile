# Agentek image: the upstream server in agentek.main mode. Build context is the repository root.
# Read-only root: FASTMCP_HOME moves FastMCP's own files to /tmp (an emptyDir in k8s).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    PORT=8000 \
    FASTMCP_HOME=/tmp/fastmcp

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY py-core py-core
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev && useradd --create-home --uid 1000 app

USER app
EXPOSE 8000

LABEL org.opencontainers.image.source="https://github.com/windbit/agentek-google-mcp"

HEALTHCHECK --start-period=30s --interval=10s --timeout=5s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health',timeout=4)"]

CMD ["/app/.venv/bin/python", "-m", "agentek.main"]
