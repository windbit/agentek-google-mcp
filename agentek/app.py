"""Agentek mode on top of the upstream server: py-core OAuth proxy, identity tool and tool filter."""

import os

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token
from mcp.types import ToolAnnotations
from windbit_core.mcp.consent import ConsentAppearance
from windbit_core.mcp.oauth_proxy import OAuthProxyProvider, ProxyOptions
from windbit_core.mcp.store import MemoryOAuthStore

from agentek import errors
from agentek.google_adapter import GoogleAdapter
from agentek.scopes import REQUIRED_SCOPES_OVERRIDE
from agentek.tool_filter import GrantedScopesToolFilter
from core.tool_registry import get_tool_components

MCP_SCOPE = "google"


def install(server: FastMCP, *, adapter: GoogleAdapter | None = None) -> None:
    errors.enable()
    server.auth = OAuthProxyProvider(
        ProxyOptions(
            public_url=_env("PUBLIC_URL"),
            scopes=[MCP_SCOPE],
            consent=ConsentAppearance(
                brand_name="Agentek",
                service_name="Google",
                cookie_prefix="google",
                authorization_origins=["https://accounts.google.com"],
                permission_names={
                    MCP_SCOPE: "Сервисы Google, которые вы отметите на следующем шаге"
                },
                extra_permissions=[
                    "Google Документы, Таблицы и Презентации, к которым у вас есть доступ",
                    "Файлы Google Диска, созданные агентом",
                    "Календари, контакты, задачи и формы",
                ],
                provider_hint="На экране Google отметьте сервисы для агента или нажмите «Выбрать всё».",
            ),
            allowed_redirect_uris=_env_list("MCP_ALLOWED_REDIRECT_URIS"),
            trusted_cidrs=_env_list("MCP_TRUSTED_CIDRS", required=False),
        ),
        adapter=adapter
        or GoogleAdapter(
            client_id=_env("GOOGLE_OAUTH_CLIENT_ID"),
            client_secret=_env("GOOGLE_OAUTH_CLIENT_SECRET"),
        ),
        store=MemoryOAuthStore(),
    )
    required = {
        name: list(getattr(getattr(tool, "fn", tool), "_required_google_scopes", []))
        for name, tool in get_tool_components(server).items()
    }
    required.update(REQUIRED_SCOPES_OVERRIDE)
    server.add_middleware(GrantedScopesToolFilter(required))
    server.tool(
        name="google_get_self",
        title="Подключённый аккаунт Google",
        annotations=ToolAnnotations(
            readOnlyHint=True, idempotentHint=True, openWorldHint=False
        ),
    )(google_get_self)


async def google_get_self() -> dict:
    """ID and email of the Google account connected to the agent."""
    token = get_access_token()
    claims = getattr(token, "claims", None) or {}
    return {"sub": claims.get("sub"), "email": claims.get("email")}


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _env_list(name: str, *, required: bool = True) -> list[str]:
    raw = os.environ.get(name, "")
    if required and not raw.strip():
        raise RuntimeError(f"{name} is required")
    return [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]
