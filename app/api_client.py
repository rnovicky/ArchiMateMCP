"""
The server's client of the ArchiMate API (/api/v2).

Every tool goes through ApiClient. A failed request becomes an ApiError, a
ToolError of the MCP SDK, so that its message (the API's own, where it gave
one) reaches the assistant, which can then correct its call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx2 as httpx
from mcp.server.mcpserver.exceptions import ToolError

from app.config import Settings
from app.version import APP_VERSION, MIN_API_VERSION


class ApiError(ToolError):
    """A request to the API failed: no answer, or an answer with an error status."""

    def __init__(self, message: str, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class ApiStatus:
    """What the start-up check found: the API's version and the key in use."""

    url: str
    version: str
    key_name: str
    role: str
    permissions: list[str]
    key_label: str | None = None
    # API 3.21.0: it refuses (428) a change of an existing item that says no version (REQUIRE_IF_MATCH); None
    # from an older API, which does not say
    require_if_match: bool | None = None


def version_tuple(version: str) -> tuple[int, ...]:
    """'3.2.0' -> (3, 2, 0); anything after the numbers ('3.2.0rc1') is ignored."""
    parts = []
    for part in version.split("."):
        digits = ""
        for ch in part:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _message(response: httpx.Response) -> tuple[str, Any]:
    """
    The API's error message. The API answers {code, message} with, for a 422, `details` (what is wrong
    with which parameter) and, for a 409 of the import, `candidates`; FastAPI's own {detail} is read too.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:500] or response.reason_phrase, None
    if not isinstance(body, dict):
        return str(body)[:500], body
    if body.get("message") is not None:
        message = str(body["message"])
        if body.get("details"):
            message += " " + "; ".join(str(d) for d in body["details"])
        if body.get("candidates"):
            listed = "; ".join(f"{c.get('name')} (id {c.get('id')})" for c in body["candidates"] if isinstance(c, dict))
            message += f" Candidates: {listed}."
        if body.get("code") == "PRECONDITION_FAILED":
            message += changed_by(body.get("lastChange"))
        return message, body
    detail = body.get("detail")
    if isinstance(detail, str):
        return detail, body
    if isinstance(detail, list):  # FastAPI's validation errors
        parts = []
        for d in detail:
            if isinstance(d, dict):
                where = ".".join(str(x) for x in d.get("loc", []) if x != "body")
                parts.append(f"{where}: {d.get('msg')}" if where else str(d.get("msg")))
        return "; ".join(parts) or str(detail), body
    return str(body)[:500], body


def changed_by(entry: Any) -> str:
    """API 3.12.0: the last change of an item a stale write was refused for, as a sentence."""
    if not isinstance(entry, dict):
        return ""
    who = entry.get("user") or "someone"
    if entry.get("client"):
        who += f" with {entry['client']}"
    what = ""
    after = entry.get("after")
    if entry.get("op") == "update" and isinstance(after, dict) and after:
        before = entry.get("before") or {}
        what = ": " + ", ".join(f"{k} {before.get(k)!r} -> {v!r}" for k, v in list(after.items())[:5])
    elif entry.get("kind") == "property" and entry.get("name"):
        what = f": property \"{entry['name']}\" ({entry.get('op')})"
    else:
        what = f" ({entry.get('op')} of the {entry.get('kind')})"
    return f" Last change by {who} at {entry.get('time')}{what}."


class ApiClient:
    """Asynchronous requests to /api/v2 with the configured key."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    @property
    def _client(self) -> httpx.AsyncClient:
        # Made on first use, and again after aclose(): its connections belong to
        # the event loop they were opened in (the start-up check runs in its own).
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self.settings.api_url.rstrip("/"),
                # X-Client: the API's record of changes names the client (3.11.0)
                headers={"X-API-Key": self.settings.api_key, "User-Agent": f"ArchiMateMCP/{APP_VERSION}",
                         "X-Client": f"ArchiMate MCP {APP_VERSION}"},
                timeout=self.settings.api_timeout,
                transport=self._transport,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def request(self, method: str, path: str, *, params: dict | None = None, json: Any = None,
                      if_match: str | None = None) -> Any:
        """
        `path` is below /api/v2 ("/models"), or absolute from the root ("/health"). `if_match`: the version
        of the item the write is based on (API 3.12.0); the API refuses the write (412) when it changed.
        """
        url = path if path == "/health" else "/api/v2" + path
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        headers = {"If-Match": f'"{if_match}"'} if if_match else None
        try:
            response = await self._client.request(method, url, params=params, json=json, headers=headers)
        except httpx.TimeoutException as e:
            raise ApiError(f"The ArchiMate API at {self.settings.api_url} did not answer within "
                           f"{self.settings.api_timeout:g} s.") from e
        except httpx.RequestError as e:
            raise ApiError(f"The ArchiMate API at {self.settings.api_url} cannot be reached ({e}). "
                           "Is it running, and is API_URL right?") from e
        if response.status_code >= 400:
            message, body = _message(response)
            which = "the key you sent" if self.settings.client_keys else "the key (API_KEY)"
            if response.status_code == 401:
                message = f"The ArchiMate API refused {which}: {message}"
            elif response.status_code == 403:
                message = f"{which[0].upper()}{which[1:]} may not do this: {message}"
            raise ApiError(f"{response.status_code}: {message}", response.status_code, body)
        if response.status_code == 204 or not response.content:
            return None
        if "json" in response.headers.get("content-type", ""):
            return response.json()
        return response.text

    async def get(self, path: str, **params: Any) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, body: Any, **params: Any) -> Any:
        return await self.request("POST", path, params=params, json=body)

    async def put(self, path: str, body: Any, if_match: str | None = None) -> Any:
        return await self.request("PUT", path, json=body, if_match=if_match)

    async def delete(self, path: str, if_match: str | None = None) -> Any:
        return await self.request("DELETE", path, if_match=if_match)

    def stream(self, path: str, **params: Any):
        """
        An answer that stays open (the API's change events, 3.17.0), as an async context manager of the httpx
        response: its status is not checked here, and nothing waits for the next line to come.
        """
        params = {k: v for k, v in params.items() if v is not None}
        return self._client.stream("GET", "/api/v2" + path, params=params, headers={"Accept": "text/event-stream"},
                                   timeout=httpx.Timeout(self.settings.api_timeout, read=None))

    async def check(self) -> ApiStatus:
        """The API answers, is new enough, and takes the key. Raises ApiError otherwise."""
        if not self.settings.api_key:
            raise ApiError("No API key: set API_KEY in .env (a key of the ArchiMate API; the role reader is enough "
                           "for reading).")
        version = await self.check_version()
        me = await self.get("/auth/me")
        return ApiStatus(self.settings.api_url, version, me["name"], me["role"], list(me.get("permissions", [])),
                         me.get("keyLabel"), me.get("requireIfMatch"))

    async def check_version(self) -> str:
        """The API answers and is new enough; its version. Raises ApiError otherwise."""
        health = await self.request("GET", "/health")
        version = str((health or {}).get("version", ""))
        if "v2" not in (health or {}).get("apiVersions", []):
            raise ApiError(f"{self.settings.api_url} does not serve /api/v2. Is API_URL the ArchiMate API?")
        if version_tuple(version) < version_tuple(MIN_API_VERSION):
            raise ApiError(f"The ArchiMate API at {self.settings.api_url} is {version or 'of an unknown version'}; "
                           f"this server needs {MIN_API_VERSION} or newer.")
        return version
