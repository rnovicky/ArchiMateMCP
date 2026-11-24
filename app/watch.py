"""
MU-15 (1.11.0): resources that announce their change (the API's
EPIC_STAGE3_DECISIONS.md, U10).

A client subscribes to resources (resources.py): with `subscriptions/listen`
(protocol 2026-07-28) or, on older protocol versions, `resources/subscribe`.
While any client of this server holds a subscription, the server listens to
the API's change events (`GET /api/v2/events`, API 3.17.0) on one stream, and
tells each subscriber that a resource it subscribed to may have changed:

  archimate://models                     by every change of any model (its revisions change)
  archimate://models/{model}/...         by every change of that model: an element's
                                         answer holds its relationships, properties and
                                         views, a view's the names of its elements
  archimate://metamodel                  never

The notification says "read it again", not what changed. Nobody subscribed:
no stream. An API without events (404) is not asked again until the server
starts anew; tools read fresh on every call and are not concerned.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx2 as httpx
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler, ResourceUpdated
from mcp_types import EmptyResult, SubscribeRequestParams, SubscriptionsListenRequestParams, UnsubscribeRequestParams

from app.api_client import ApiClient, ApiError
from app.lookup import Lookup

logger = logging.getLogger(__name__)

MODELS = "archimate://models"
ITEM = re.compile(r"^archimate://models/([^/]+)/(?:views|elements)/[^/]+$")
RETRY = 3.0        # s before opening a dropped stream again
MAX_RETRY = 60.0   # s at most between attempts while the API cannot be reached


class Watcher:
    """The subscriptions of one server's clients, and the API's change events while there are any."""

    def __init__(self, api: ApiClient, lookup: Lookup):
        self.api, self.lookup = api, lookup
        self.bus = InMemorySubscriptionBus()
        # token -> (the URIs, how to tell: None for listen streams, which the bus serves; else a callable)
        self.subscriptions: dict[object, tuple[frozenset[str], Callable[[str], Awaitable[Any]] | None]] = {}
        self.model_of: dict[str, int | None] = {}  # a subscribed item URI -> its model's id
        self.last_id: int | None = None
        self.off = False  # the API has no change events (before 3.17.0, or EVENTS=false)
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------ subscriptions

    async def add(self, uris: frozenset[str], tell: Callable[[str], Awaitable[Any]] | None = None) -> object:
        for uri in uris:
            match = ITEM.match(uri)
            if match and uri not in self.model_of:
                try:
                    self.model_of[uri] = (await self.lookup.model(match.group(1)))["id"]
                except ApiError:
                    self.model_of[uri] = None  # no such model: never told
        token = object()
        self.subscriptions[token] = (uris, tell)
        if not self.off and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._run(), name="ArchiMate change events")
        return token

    def remove(self, token: object) -> None:
        self.subscriptions.pop(token, None)
        if not self.subscriptions and self._task is not None:
            self._task.cancel()
            self._task = None
            self.last_id = None

    def affected(self, model_id: int | None) -> set[str]:
        """The subscribed URIs a change of this model touches (None: any model, after a gap)."""
        uris = set().union(*(u for u, _ in self.subscriptions.values())) if self.subscriptions else set()
        return {u for u in uris if u == MODELS or (u in self.model_of and (model_id is None or self.model_of[u] == model_id))}

    async def tell(self, uris: set[str]) -> None:
        for uri in sorted(uris):
            await self.bus.publish(ResourceUpdated(uri=uri))
        for token, (subscribed, tell) in list(self.subscriptions.items()):
            if tell is None:
                continue
            for uri in sorted(uris & subscribed):
                try:
                    await tell(uri)
                except Exception:  # the session is gone: its subscriptions with it
                    self.subscriptions.pop(token, None)
                    break

    # ------------------------------------------------------------ the API's events

    async def _run(self) -> None:
        failures = 0
        while self.subscriptions:
            try:
                async with self.api.stream("/events", after=self.last_id) as resp:
                    if resp.status_code in (404, 401, 403):
                        self.off = True
                        logger.warning("The ArchiMate API gives no change events (%s): subscribers are not told of "
                                       "changes. It needs API 3.17.0 with EVENTS=true.", resp.status_code)
                        return
                    if resp.status_code != 200:
                        await resp.aread()
                        wait = float(resp.headers.get("Retry-After") or MAX_RETRY)
                        await asyncio.sleep(min(wait, MAX_RETRY))
                        continue
                    failures = 0
                    await self._read(resp)
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, OSError, ValueError) as e:
                logger.info("The ArchiMate API's change events dropped (%s); opening them again.", e)
                failures += 1
            await asyncio.sleep(min(RETRY * 2 ** max(failures - 1, 0), MAX_RETRY))

    async def _read(self, resp: httpx.Response) -> None:
        event: dict[str, Any] = {}
        async for line in resp.aiter_lines():
            if line.startswith(":"):
                continue
            if line:
                field, _, value = line.partition(":")
                event[field] = value[1:] if value.startswith(" ") else value
                continue
            if "data" in event:
                await self._event(event)
            event = {}

    async def _event(self, event: dict[str, Any]) -> None:
        if event.get("id", "").isdigit():
            self.last_id = int(event["id"])
        kind = event.get("event")
        if kind == "reset":  # what came meanwhile cannot be told: everything may have changed
            await self.tell(self.affected(None))
        elif kind == "change":
            data = json.loads(event["data"])
            await self.tell(self.affected(data.get("modelId")))


class Listen(ListenHandler):
    """`subscriptions/listen`, noting which resources the stream wants while it is open."""

    def __init__(self, watcher: Watcher):
        super().__init__(watcher.bus)
        self.watcher = watcher

    async def __call__(self, ctx, params):
        uris = frozenset(params.notifications.resource_subscriptions or ())
        token = await self.watcher.add(uris) if uris else None
        try:
            return await super().__call__(ctx, params)
        finally:
            if token is not None:
                self.watcher.remove(token)


def install(server, watcher: Watcher) -> None:
    """Both ways to subscribe on the server's request handlers (the SDK's own listen handler replaced)."""
    lowlevel = server._lowlevel_server  # noqa: SLF001  (MCPServer has no public way to add these)
    lowlevel.add_request_handler("subscriptions/listen", SubscriptionsListenRequestParams, Listen(watcher))
    legacy: dict[tuple[int, str], object] = {}

    def connection(ctx):
        """The client's connection: the session of a request lasts as long as the request."""
        return ctx.session._connection  # noqa: SLF001

    async def subscribe(ctx, params: SubscribeRequestParams) -> EmptyResult:
        key = (id(connection(ctx)), params.uri)
        if legacy.get(key) not in watcher.subscriptions:  # new, or dropped with a connection gone
            legacy[key] = await watcher.add(frozenset({params.uri}), connection(ctx).send_resource_updated)
        return EmptyResult()

    async def unsubscribe(ctx, params: UnsubscribeRequestParams) -> EmptyResult:
        token = legacy.pop((id(connection(ctx)), params.uri), None)
        if token is not None:
            watcher.remove(token)
        return EmptyResult()

    lowlevel.add_request_handler("resources/subscribe", SubscribeRequestParams, subscribe)
    lowlevel.add_request_handler("resources/unsubscribe", UnsubscribeRequestParams, unsubscribe)

