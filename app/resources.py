"""
MCP-12: resources, the read-only data a client may attach to a conversation
(the user picks them, unlike tools, which the assistant calls).

  archimate://metamodel                                the layers and their element types, the relationship
                                                       types, how the impact analysis propagates a change
  archimate://models                                   the models
  archimate://models/{model}/views/{view}              a view, as get_view answers
  archimate://models/{model}/elements/{element}        an element, as get_element answers

{model}, {view} and {element} are ids.

1.11.0 (MU-15): a client may subscribe to them; app/watch.py tells it when they may have changed.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from app.tools import Context
from app.tools.concepts import describe_element
from app.tools.views import describe_view

JSON = "application/json"


def _text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def register(server: MCPServer, ctx: Context) -> None:
    api, lookup = ctx.api, ctx.lookup

    @server.resource("archimate://metamodel", name="metamodel", title="ArchiMate metamodel", mime_type=JSON,
                     description="The layers with their element types, the relationship types, and how the "
                                 "impact analysis lets a change propagate along each of them (the ArchiMate API's).")
    async def metamodel() -> str:
        return _text(await api.get("/metamodel"))

    @server.resource("archimate://models", name="models", title="ArchiMate models", mime_type=JSON,
                     description="The models the ArchiMate API holds: id, name, XMI identifier, revision.")
    async def models() -> str:
        return _text([{"id": m["id"], "name": m["name"], "xmiIdentifier": m.get("xmiIdentifier"),
                       "revision": m.get("revision")} for m in await lookup.models()])

    @server.resource("archimate://models/{model}/views/{view}", name="view", title="ArchiMate view", mime_type=JSON,
                     description="What a view shows: elements, relationships, groups, notes, links (no coordinates).")
    async def view(model: str, view: str) -> str:
        return _text(await describe_view(ctx, model, view))

    @server.resource("archimate://models/{model}/elements/{element}", name="element", title="ArchiMate element",
                     mime_type=JSON, description="An element with its properties, folders, relationships and views.")
    async def element(model: str, element: str) -> str:
        return _text(await describe_element(ctx, model, element))
