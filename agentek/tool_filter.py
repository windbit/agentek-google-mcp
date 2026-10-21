from fastmcp.exceptions import NotFoundError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool

from agentek.scopes import granted_apis, tool_visible


class GrantedScopesToolFilter(Middleware):
    """The agent lists and calls only tools of the services the user granted.

    `required` maps a tool to the scopes it declares upstream (`_required_google_scopes`);
    a tool missing from it does not depend on Google services and is always visible.
    """

    def __init__(self, required: dict[str, list[str]]) -> None:
        self._required = required

    async def on_list_tools(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> list[Tool]:
        tools = await call_next(context)
        granted = _granted()
        return [
            tool
            for tool in tools
            if tool_visible(self._required.get(tool.name, []), granted)
        ]

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        name = context.message.name
        if not tool_visible(self._required.get(name, []), _granted()):
            raise NotFoundError(f"Unknown tool: {name}")
        return await call_next(context)


def _granted() -> set[str]:
    token = get_access_token()
    claims = getattr(token, "claims", None) or {}
    return granted_apis(claims.get("provider_scopes", []))
