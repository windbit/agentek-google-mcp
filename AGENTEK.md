# Agentek fork

> For developers of this fork: how it runs as the Google integration of the Agentek platform and what differs from upstream. Decisions and their reasons live in [windbit/issues#2244](https://github.com/windbit/issues/issues/2244) and in the `google-drive-mcp-integration` OpenSpec change of agentek-console.

**This fork is the Google integration of Agentek: the external OAuth 2.1 mode of upstream is replaced with the OAuth proxy from [windbit/py-core](https://github.com/windbit/py-core).** The proxy registers clients itself, shows the Agentek consent screen and hands Google tokens to Hermes as they are. Hermes stores and refreshes them; the server writes nothing to disk. The image serves Drive, Docs, Sheets, Slides, Calendar, Contacts, Tasks and Forms; `Dockerfile` sets the mode.

## What differs from upstream

Changes live directly in upstream files, each in a block marked `Agentek integration`:

- `core/server.py` — in external mode `configure_server_for_http` installs the py-core proxy, the granted-scope tool filter and the `google_get_self` identity tool (`sub` and email for the console connection card), switches to JSON logs and silences the uvicorn access log, which would print OAuth codes from query strings.
- `auth/external_oauth_provider.py` — `GoogleProxyAdapter`: Google sign-in, code exchange, refresh and access token checks via tokeninfo with our client ID as the expected audience. Google errors map to py-core kinds: 429 and 5xx are temporary, `invalid_grant` needs a new sign-in, anything else — including `invalid_client` after a secret rotation — is a failure on our side.
- `auth/scopes.py` — requested scopes and tool visibility. The user ticks services on the Google consent screen (the ticks are off by default) and the agent sees tools of the ticked services only. Visibility compares APIs rather than exact scopes: upstream declares `drive.readonly` on Drive tools, but they work with `drive.file` within the integration's own files.
- `core/tool_registry.py` — FastMCP middleware applying that rule to `tools/list` and `tools/call`.
- `gdrive/drive_helpers.py`, `gdocs/docs_tools.py` — `drive.file` fixes: the Drive root without a metadata lookup, shared Docs opened through the Docs API, comments skipped when Drive hides them.
- `core/utils.py` — Agentek error texts for the agent (file unavailable to the integration, Google temporarily unavailable), on only in Agentek mode.
- `.github/workflows/pytest.yml`, `docker-publish.yml` — our runners and the `py-core` submodule.
- Tests replaced: upstream tests of `ExternalOAuthProvider` wiring are removed; `tests/auth/test_agentek_mode.py` covers the Agentek mode, including an end-to-end sign-in against a fake Google.

## Running

The server needs these variables and fails at startup without a required one:

```sh
PUBLIC_URL=https://google-mcp.k.agentek.ru            # issuer, /mcp and the /oauth/callback address for Google
GOOGLE_OAUTH_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=...
MCP_ALLOWED_REDIRECT_URIS=https://console.agentek.ru/api/agents/*/mcp/*/oauth/*/callback
MCP_TRUSTED_CIDRS=203.0.113.0/24                      # optional: cluster node egress exempt from limits
```

The image runs with a read-only root filesystem and writes only to `/tmp`, where `FASTMCP_HOME` also points. Readiness is `GET /health`.

## Updating upstream

An update is a `git merge` of an upstream tag into `main`; conflicts can appear only in the files listed above. After merging run the whole suite.

```sh
git fetch upstream --tags
git merge v2.2.0
uv sync && uv run pytest -q tests
```

## Rotating the OAuth client secret

While the server still uses the old secret and Google no longer accepts it, refresh gets `invalid_client` from Google. The proxy turns it into 503, so Hermes keeps its connections and retries. Create a new secret in Google Cloud without deleting the old one, seal it into the SealedSecret and wait for the pod to restart, then delete the old secret.
