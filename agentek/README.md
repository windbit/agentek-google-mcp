# Agentek mode

> For developers of this fork: how the upstream server runs as the Google integration of the Agentek platform, and what is ours here. Decisions and their reasons live in [windbit/issues#2244](https://github.com/windbit/issues/issues/2244) and in the `google-drive-mcp-integration` OpenSpec change of agentek-console.

**The Agentek image starts the upstream server through `agentek.main` and touches upstream files only where there is no other way.** The entry point enables stateless external OAuth 2.1 mode, keeps Drive, Docs, Sheets, Slides, Calendar, Contacts, Tasks and Forms, and swaps the upstream auth provider for the OAuth proxy from [windbit/py-core](https://github.com/windbit/py-core). The proxy registers clients itself, shows the Agentek consent screen and hands Google tokens to Hermes as they are. Hermes stores and refreshes them; the MCP server writes nothing to disk.

## What is ours

Agentek code lives in `agentek/`:

- `google_adapter.py` — Google sign-in, code exchange, refresh and access token checks via tokeninfo with our client ID as the expected audience. Google errors map to py-core kinds: 429 and 5xx are temporary, `invalid_grant` needs a new sign-in, anything else — including `invalid_client` after a secret rotation — is a failure on our side.
- `scopes.py` — requested scopes and tool visibility. The user ticks services on the Google consent screen and the agent sees tools of the ticked services only. Visibility compares APIs rather than exact scopes: upstream declares `drive.readonly` on Drive tools, but they work with `drive.file` within the integration's own files.
- `tool_filter.py` — FastMCP middleware applying that rule to `tools/list` and `tools/call`.
- `app.py` — wiring: the proxy, the filter and the `google_get_self` identity tool (`sub` and email for the connection card in the console).
- `drive_fallback.py` and `errors.py` — `drive.file` workarounds and error texts.

Upstream files changed: `gdrive/drive_helpers.py` (the Drive root without a metadata lookup, which returns 404 under `drive.file`), `gdocs/docs_tools.py` (metadata and comments of a shared document through the Docs API), `core/utils.py` (the hook for Agentek error texts, off outside Agentek mode).

## Running

The server needs these variables and fails at startup without any required one:

```sh
PUBLIC_URL=https://google-mcp.k.agentek.ru            # issuer, /mcp and the /oauth/callback address for Google
GOOGLE_OAUTH_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=...
MCP_ALLOWED_REDIRECT_URIS=https://console.agentek.ru/api/agents/*/mcp/*/oauth/*/callback
MCP_TRUSTED_CIDRS=203.0.113.0/24                      # optional: cluster node egress exempt from limits
uv run python -m agentek.main
```

The image builds from `agentek/Dockerfile` with the repository root as context and runs with a read-only root filesystem. It writes only to `/tmp`, where `FASTMCP_HOME` also points. Readiness is `GET /health`.

## Updating upstream

An update is a `git merge` of an upstream tag into `main`. Conflicts can only appear in the three files listed above. After merging run the whole suite; `tests/agentek/` shows whether Agentek mode broke.

```sh
git fetch upstream --tags
git merge v2.2.0
uv sync && uv run pytest -q tests
```

## Rotating the OAuth client secret

While the server still uses the old secret and Google no longer accepts it, refresh gets `invalid_client` from Google. The proxy turns it into 503 for clients, so Hermes keeps its connections and retries. The order: create a new secret in Google Cloud without deleting the old one; seal it into the SealedSecret and wait for the pod to restart; then delete the old secret in Google Cloud.
