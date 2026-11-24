"""
The HTTP transport (MCP streamable HTTP) at /mcp. GET /health answers without
a key or token, for scripts that check the server runs. Two ways in:

* MCP_TOKEN: every client sends the server's own token ("Authorization:
  Bearer <token>") and the server uses its own API key for everyone.
* CLIENT_KEYS=true (MU-2, 1.7.0): every client sends its own key of the
  ArchiMate API ("Authorization: Bearer <API key>"). The server checks it
  with the API, and serves that client with a server of its own around that
  key: the API, and its record of changes, see the person, and the write
  tools follow their role.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Callable

import anyio
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import LOOPBACK_HOSTS, Settings
from app.version import APP_VERSION

logger = logging.getLogger("app.http")

MCP_PATH = "/mcp"


def _unauthorized(description: str) -> JSONResponse:
    return JSONResponse({"error": "invalid_token", "error_description": description}, status_code=401,
                        headers={"WWW-Authenticate": 'Bearer realm="archimate-mcp"'})


def _bearer(scope: Scope) -> bytes:
    header = dict(scope["headers"]).get(b"authorization", b"")
    scheme, _, given = header.partition(b" ")
    return given.strip() if scheme.lower() == b"bearer" else b""


async def _health(scope: Scope, receive: Receive, send: Send) -> None:
    await JSONResponse({"status": "ok", "server": "ArchiMate MCP", "version": APP_VERSION})(scope, receive, send)


class TokenRequired:
    """ASGI middleware: every HTTP request but GET /health needs the bearer token."""

    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self.token = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self.token and scope["path"] != "/health":
            if not hmac.compare_digest(_bearer(scope), self.token):
                await _unauthorized("Send the server's MCP_TOKEN as: Authorization: Bearer <token>")(scope, receive, send)
                return
        await self.app(scope, receive, send)


class ClientKeys:
    """
    ASGI app for CLIENT_KEYS=true: one MCP server per API key that clients send. A server is made the
    first time its key comes (after the API has said whose key it is) and kept while this app runs; its
    MCP sessions live in it. A key the API refuses later makes that client's tools fail with the API's
    answer.
    """

    def __init__(self, settings: Settings, make_server: Callable[[Settings], Any]):
        self.settings = settings
        self.make_server = make_server  # async (settings with the client's key) -> (MCPServer, ApiStatus)
        self.apps: dict[str, ASGIApp] = {}
        self._lock = anyio.Lock()
        self._tg: anyio.abc.TaskGroup | None = None
        self._stop = anyio.Event()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope["type"] != "http":
            return
        if scope["path"] == "/health":
            await _health(scope, receive, send)
            return
        key = _bearer(scope).decode(errors="replace")
        if not key:
            await _unauthorized("Send your own key of the ArchiMate API as: Authorization: Bearer <API key>")(
                scope, receive, send)
            return
        try:
            app = await self._app_for(key)
        except _Refused as e:
            await _unauthorized(str(e))(scope, receive, send)
            return
        except _Unavailable as e:
            await JSONResponse({"error": "api_unavailable", "error_description": str(e)}, status_code=503)(
                scope, receive, send)
            return
        await app(scope, receive, send)

    async def _app_for(self, key: str) -> ASGIApp:
        digest = hashlib.sha256(key.encode()).hexdigest()
        async with self._lock:
            app = self.apps.get(digest)
            if app is not None:
                return app
            from app.api_client import ApiError

            try:
                server, status = await self.make_server(self.settings.model_copy(update={"api_key": key}))
            except ApiError as e:
                if e.status in (401, 403):
                    raise _Refused(f"The ArchiMate API refused the key: {e}") from e
                raise _Unavailable(str(e)) from e
            app = server.streamable_http_app(streamable_http_path=MCP_PATH, host=self.settings.host)
            await self._tg.start(self._run, app)
            self.apps[digest] = app
            logger.info("A client with the key of \"%s\" (%s) connected.", status.key_name, status.role)
            return app

    async def _run(self, app, *, task_status=anyio.TASK_STATUS_IGNORED) -> None:
        """Runs one server's sessions until this app stops (its lifespan, in a task of its own)."""
        async with app.router.lifespan_context(app):
            task_status.started()
            await self._stop.wait()

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        await receive()  # lifespan.startup
        async with anyio.create_task_group() as tg:
            self._tg = tg
            await send({"type": "lifespan.startup.complete"})
            await receive()  # lifespan.shutdown
            self._stop.set()
        await send({"type": "lifespan.shutdown.complete"})


class _Refused(Exception):
    pass


class _Unavailable(Exception):
    pass


def check_http_settings(settings: Settings) -> None:
    """Refuse a server reachable from other machines without a token or the clients' own keys."""
    if settings.client_keys and settings.mcp_token:
        raise SystemExit("Set MCP_TOKEN or CLIENT_KEYS=true, not both: with CLIENT_KEYS every client sends its own "
                         "API key, and there is no shared token.")
    if not settings.mcp_token and not settings.client_keys and settings.host not in LOOPBACK_HOSTS:
        raise SystemExit(f"HOST is {settings.host}, so other machines can reach the server: set CLIENT_KEYS=true "
                         "(every client sends its own API key) or MCP_TOKEN in .env (clients send it as "
                         "\"Authorization: Bearer <token>\").")


def http_app(server: MCPServer, settings: Settings) -> ASGIApp:
    @server.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": "ArchiMate MCP", "version": APP_VERSION})

    app = server.streamable_http_app(streamable_http_path=MCP_PATH, host=settings.host)
    return TokenRequired(app, settings.mcp_token) if settings.mcp_token else app
