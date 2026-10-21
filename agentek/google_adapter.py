"""Google adapter for the py-core OAuth proxy: sign-in, code exchange, refresh and access token checks."""

import asyncio
import logging
from urllib.parse import urlencode

import httpx
from mcp.shared.auth import OAuthToken
from windbit_core.mcp.oauth_proxy import GrantRejectedError, Identity, ProviderError

from agentek.scopes import REQUESTED_SCOPES, SERVICE_SCOPES

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
HTTP_TIMEOUT_SECONDS = 15
VERIFY_CONCURRENCY = 16
MIN_ACCESS_TOKEN_LENGTH = 40

logger = logging.getLogger(__name__)


class GoogleAdapter:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http or httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS)
        self._verify_slots = asyncio.Semaphore(VERIFY_CONCURRENCY)

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        query = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(REQUESTED_SCOPES),
            "access_type": "offline",
            # Without prompt=consent Google issues no refresh token when the same account signs in again.
            "prompt": "consent",
            "include_granted_scopes": "false",
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    def callback_context(self, query: dict[str, str]) -> list[str]:
        granted = query.get("scope", "").split()
        if not any(scope in SERVICE_SCOPES for scope in granted):
            # No revoke here: Google revokes the whole account grant, cutting off every connected agent.
            raise GrantRejectedError(
                "Google не выдал доступ ни к одному сервису",
                "Повторите вход и на экране Google отметьте сервисы, с которыми должен работать агент, "
                "или нажмите «Выбрать всё».",
            )
        return granted

    async def exchange_code(
        self, *, code: str, redirect_uri: str, context: list[str]
    ) -> OAuthToken:
        return await self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            }
        )

    async def refresh(self, refresh_token: str) -> OAuthToken:
        return await self._token(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    async def _token(self, grant: dict[str, str]) -> OAuthToken:
        form = {
            **grant,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        try:
            response = await self._http.post(TOKEN_URL, data=form)
        except httpx.HTTPError as error:
            raise ProviderError("temporary", type(error).__name__) from None
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderError("temporary", f"HTTP {response.status_code}")
        body = response.json()
        if response.status_code != 200:
            error = body.get("error")
            # invalid_client from Google means a rotated or deleted secret: our failure, not the client's.
            raise ProviderError(
                "invalid_grant" if error == "invalid_grant" else "misconfigured",
                str(error),
            )
        return OAuthToken.model_validate(
            {key: value for key, value in body.items() if key != "id_token"}
        )

    async def verify(self, token: str) -> Identity | None:
        if not token.startswith("ya29.") or len(token) < MIN_ACCESS_TOKEN_LENGTH:
            return None
        async with self._verify_slots:
            try:
                response = await self._http.post(
                    TOKENINFO_URL, data={"access_token": token}
                )
            except httpx.HTTPError as error:
                raise ProviderError("temporary", type(error).__name__) from None
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderError("temporary", f"HTTP {response.status_code}")
        if response.status_code != 200:
            return None
        info = response.json()
        if info.get("aud") != self._client_id or not info.get("sub"):
            return None
        return Identity(
            subject=info["sub"],
            claims={
                "sub": info["sub"],
                "email": info.get("email"),
                "provider_scopes": info.get("scope", "").split(),
            },
        )
