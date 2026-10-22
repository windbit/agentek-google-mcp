import base64
import hashlib
import json
import logging
import secrets
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from fastmcp import FastMCP
from googleapiclient.errors import HttpError
from httplib2 import Response
from windbit_core.mcp.oauth_proxy import GrantRejectedError, ProviderError

from auth.external_oauth_provider import GoogleProxyAdapter as GoogleAdapter
from auth.scopes import granted_apis, tool_visible
from core import utils as errors
from core.server import (
    AGENTEK_QUIET_LOGGERS,
    build_agentek_oauth_proxy,
    configure_agentek_mode,
)
from gdocs.docs_tools import _document_metadata as document_metadata

PUBLIC = "https://testserver"
CONSOLE_CB = "https://console.example/api/agents/1/mcp/google/oauth/a1/callback"
CLIENT_ID = "client-1.apps.googleusercontent.com"
G = "https://www.googleapis.com/auth/"
VALID_TOKEN = "ya29." + "a" * 60


def google(scopes: str = f"{G}documents openid {G}userinfo.email"):
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        if request.url.path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": VALID_TOKEN,
                    "refresh_token": "1//r",
                    "expires_in": 3599,
                },
            )
        if request.url.path == "/tokeninfo":
            if form["access_token"][0] != VALID_TOKEN:
                return httpx.Response(400, json={"error": "invalid_token"})
            return httpx.Response(
                200,
                json={
                    "aud": CLIENT_ID,
                    "sub": "1055",
                    "email": "u@example.com",
                    "scope": scopes,
                },
            )
        raise AssertionError(request.url)

    return GoogleAdapter(
        client_id=CLIENT_ID,
        client_secret="s",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def fake_tool(name: str, scopes: list[str]):
    async def tool() -> str:
        return name

    tool._required_google_scopes = scopes
    tool.__name__ = name
    return tool


@pytest.fixture(autouse=True)
def restore_upstream_globals():
    # configure_agentek_mode() turns Agentek error texts on and reconfigures logging process-wide;
    # upstream tests expect their own texts and log levels.
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    quiet = {name: logging.getLogger(name).level for name in AGENTEK_QUIET_LOGGERS}
    yield
    errors._agentek_error_texts = False
    root.handlers[:] = handlers
    root.setLevel(level)
    for name, quiet_level in quiet.items():
        logging.getLogger(name).setLevel(quiet_level)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", PUBLIC)
    monkeypatch.setenv(
        "MCP_ALLOWED_REDIRECT_URIS",
        "https://console.example/api/agents/*/mcp/*/oauth/*/callback",
    )
    server = FastMCP("t")
    server.tool(
        fake_tool("get_doc_content", [f"{G}drive.readonly", f"{G}documents.readonly"])
    )
    server.tool(fake_tool("read_sheet_values", [f"{G}spreadsheets.readonly"]))
    server.auth = build_agentek_oauth_proxy(None, adapter=google())
    configure_agentek_mode(server)
    return server.http_app(path="/mcp", stateless_http=True)


@pytest.mark.asyncio
async def test_login_then_agent_sees_only_granted_services(app):
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=PUBLIC
        ) as http,
    ):
        client_id = (
            await http.post(
                "/register",
                json={
                    "redirect_uris": [CONSOLE_CB],
                    "token_endpoint_auth_method": "none",
                },
            )
        ).json()["client_id"]
        authorize = await http.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": CONSOLE_CB,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "s1",
            },
        )
        consent = await http.get(authorize.headers["location"])
        fields = {
            name: consent.text.split(f'name="{name}" value="')[1].split('"')[0]
            for name in ("id", "nonce")
        }
        allow = await http.post("/oauth/consent", data={**fields, "decision": "allow"})
        google_redirect = urlsplit(allow.headers["location"])
        assert google_redirect.netloc == "accounts.google.com"
        state = parse_qs(google_redirect.query)["state"][0]
        callback = await http.get(
            "/oauth/callback",
            params={"state": state, "code": "4/abc", "scope": f"openid {G}documents"},
        )
        code = parse_qs(urlsplit(callback.headers["location"]).query)["code"][0]
        tokens = (
            await http.post(
                "/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": client_id,
                    "redirect_uri": CONSOLE_CB,
                    "code_verifier": verifier,
                },
            )
        ).json()
        headers = {
            "Authorization": f"Bearer {tokens['access_token']}",
            "Accept": "application/json, text/event-stream",
        }
        listed = await http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers=headers,
        )
        identity = await http.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "google_get_self", "arguments": {}},
            },
            headers=headers,
        )
        hidden = await http.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "read_sheet_values", "arguments": {}},
            },
            headers=headers,
        )

    names = {tool["name"] for tool in _rpc(listed)["result"]["tools"]}
    assert names == {"get_doc_content", "google_get_self"}
    assert json.loads(_rpc(identity)["result"]["content"][0]["text"]) == {
        "sub": "1055",
        "email": "u@example.com",
    }
    assert _rpc(hidden).get("error") or _rpc(hidden)["result"].get("isError")


def _rpc(response: httpx.Response) -> dict:
    text = response.text
    if text.startswith("event:") or "data:" in text:
        text = next(
            line[5:].strip() for line in text.splitlines() if line.startswith("data:")
        )
    return json.loads(text)


def test_tool_visible_by_api_not_exact_scope():
    granted = granted_apis([f"{G}drive.file", f"{G}documents"])

    assert tool_visible([f"{G}drive.readonly", f"{G}documents.readonly"], granted)
    assert not tool_visible([f"{G}spreadsheets.readonly"], granted)
    assert tool_visible([], granted)


def test_callback_without_any_service_is_rejected():
    with pytest.raises(GrantRejectedError):
        google().callback_context({"scope": f"openid {G}userinfo.email"})


def test_callback_with_one_service_is_accepted():
    assert f"{G}documents" in google().callback_context(
        {"scope": f"openid {G}documents"}
    )


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (503, {}, "temporary"),
        (429, {}, "temporary"),
        (400, {"error": "invalid_grant"}, "invalid_grant"),
        (401, {"error": "invalid_client"}, "misconfigured"),
    ],
)
@pytest.mark.asyncio
async def test_token_errors_are_classified(status, body, kind):
    adapter = GoogleAdapter(
        client_id=CLIENT_ID,
        client_secret="s",
        http=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body))
        ),
    )
    with pytest.raises(ProviderError) as raised:
        await adapter.refresh("1//r")

    assert raised.value.kind == kind


@pytest.mark.asyncio
async def test_verify_rejects_token_of_other_client():
    adapter = GoogleAdapter(
        client_id=CLIENT_ID,
        client_secret="s",
        http=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"aud": "other", "sub": "1"})
            )
        ),
    )
    assert await adapter.verify(VALID_TOKEN) is None


@pytest.mark.asyncio
async def test_verify_skips_google_for_malformed_token():
    calls = []
    adapter = GoogleAdapter(
        client_id=CLIENT_ID,
        client_secret="s",
        http=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: calls.append(r) or httpx.Response(500)
            )
        ),
    )
    assert await adapter.verify("junk") is None
    assert calls == []


@pytest.mark.asyncio
async def test_verify_reports_temporary_failure():
    adapter = GoogleAdapter(
        client_id=CLIENT_ID,
        client_secret="s",
        http=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(503))
        ),
    )
    with pytest.raises(ProviderError):
        await adapter.verify(VALID_TOKEN)


def test_error_texts_only_in_agentek_mode(monkeypatch):
    monkeypatch.setattr(errors, "_agentek_error_texts", False)
    assert errors.agentek_http_error_message("t", 404) is None
    errors.enable_agentek_error_texts()
    assert "недоступен интеграции" in errors.agentek_http_error_message("t", 404)
    assert "временно недоступен" in errors.agentek_http_error_message("t", 503)
    assert errors.agentek_http_error_message("t", 400) is None


class _Request:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def execute(self):
        if self.error:
            raise self.error
        return self.result


class _Drive:
    def files(self):
        return self

    def get(self, **_):
        return _Request(error=HttpError(Response({"status": 404}), b"not found"))


class _Docs:
    def documents(self):
        return self

    def get(self, **_):
        return _Request(result={"title": "Чужой документ"})


@pytest.mark.asyncio
async def test_document_metadata_falls_back_to_docs_api():
    metadata = await document_metadata(_Drive(), _Docs(), "doc-1")

    assert metadata["name"] == "Чужой документ"
    assert metadata["mimeType"] == "application/vnd.google-apps.document"


def test_http_configuration_installs_agentek_proxy(monkeypatch):
    from auth.oauth_config import reload_oauth_config
    from core import server as server_module
    from windbit_core.mcp.oauth_proxy import OAuthProxyProvider

    for name, value in {
        "MCP_ENABLE_OAUTH21": "true",
        "EXTERNAL_OAUTH21_PROVIDER": "true",
        "WORKSPACE_MCP_STATELESS_MODE": "true",
        "GOOGLE_OAUTH_CLIENT_ID": CLIENT_ID,
        "GOOGLE_OAUTH_CLIENT_SECRET": "s",
        "PUBLIC_URL": PUBLIC,
        "MCP_ALLOWED_REDIRECT_URIS": CONSOLE_CB,
    }.items():
        monkeypatch.setenv(name, value)
    reload_oauth_config()
    monkeypatch.setattr(server_module, "configure_agentek_mode", lambda target: None)
    server_module.set_transport_mode("streamable-http")
    try:
        server_module.configure_server_for_http()

        assert isinstance(server_module.server.auth, OAuthProxyProvider)
        assert server_module.get_auth_provider() is server_module.server.auth
    finally:
        server_module.close_auth_provider()
        server_module.server.auth = None
        monkeypatch.undo()
        reload_oauth_config()
