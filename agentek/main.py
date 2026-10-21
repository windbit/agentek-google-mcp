"""Agentek image entry point: the upstream server in Agentek mode, without editing its `main.py`."""

import logging
import os
import sys

from windbit_core.logger import configure_logging

from agentek.scopes import SERVICES

MODE_ENV = {
    "MCP_ENABLE_OAUTH21": "true",
    # External mode: upstream keeps no tokens in its session store (auth/oauth21_session_store.py).
    "EXTERNAL_OAUTH21_PROVIDER": "true",
    "WORKSPACE_MCP_STATELESS_MODE": "true",
    "WORKSPACE_MCP_DISABLE_LOCAL_FILES": "true",
}
QUIET_LOGGERS = (
    "auth",
    "core",
    "gdrive",
    "gdocs",
    "gsheets",
    "gslides",
    "gcalendar",
    "gcontacts",
    "gtasks",
    "gforms",
)


def run() -> None:
    os.environ.update(MODE_ENV)
    os.environ.setdefault("WORKSPACE_EXTERNAL_URL", os.environ.get("PUBLIC_URL", ""))
    sys.argv = [
        "workspace-mcp",
        "--transport",
        "streamable-http",
        "--tools",
        *SERVICES,
        "--tool-tier",
        "complete",
        "--disabled-tools",
        "start_google_auth",
    ]
    import main as upstream

    from agentek.app import install
    from core.server import server

    configure_upstream = upstream.configure_server_for_http

    def configure_server_for_http() -> None:
        configure_upstream()
        install(server)
        # Upstream info logs carry user emails and file IDs.
        configure_logging("agentek-google-mcp", quiet=QUIET_LOGGERS)
        # The uvicorn access log prints query strings with OAuth codes and state; py-core logs requests instead.
        logging.getLogger("uvicorn.access").addFilter(lambda _record: False)

    upstream.configure_server_for_http = configure_server_for_http
    upstream.main()


if __name__ == "__main__":
    run()
