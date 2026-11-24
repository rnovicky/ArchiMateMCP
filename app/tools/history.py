"""
MU-16, MU-17 (1.7.0, API 3.11.0): the record of changes the API keeps.

  model_history   who changed what in a model, and when; for one item or the whole model

Offered with a key that may write (the API's role editor or admin), as the API
gives the record to editors only.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from app.tools import READ_ONLY, Context, Limit, ModelRef, Ref, compact, page

Kind = Literal["element", "relationship", "view", "folder", "property", "propertyDefinition", "model"]


def _entry(e: dict) -> dict[str, Any]:
    out = {"time": e["time"], "user": e.get("user"), "op": e["op"], "kind": e["kind"], "id": e.get("itemId"),
           "name": e.get("name"), "revision": e.get("revision")}
    for key in ("client", "keyLabel", "before", "after"):
        if e.get(key) not in (None, {}, []):
            out[key] = e[key]
    return out


def register(server: MCPServer, ctx: Context) -> None:
    api, lookup = ctx.api, ctx.lookup

    @server.tool(annotations=READ_ONLY)
    @compact
    async def model_history(
        model: ModelRef = None,
        item: Annotated[Ref | None, Field(description="Only the changes of this element, relationship or view (see "
                                                      "`kind`): id, XMI identifier or name.")] = None,
        kind: Annotated[Kind | None, Field(description="With `item`: what it is (default element). Without: only "
                                                       "changes of this kind of item.")] = None,
        user: Annotated[str | None, Field(description="Only the changes of this user.")] = None,
        since: Annotated[str | None, Field(description="From this time, ISO 8601 (\"2026-10-26\" or "
                                                       "\"2026-10-26T09:00:00Z\").")] = None,
        until: Annotated[str | None, Field(description="Before this time, ISO 8601.")] = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """Who changed what in a model, and when, newest first: each change with the user, the client (the
        ArchiMate Browser, this server, a script), the operation, the item, and the fields before and after.
        Imports and replaces are one entry each. Use it for "who changed X?", "what changed since Monday?",
        "what did I change today?"."""
        m = await lookup.model(model)
        params: dict[str, Any] = {"user": user, "since": since, "until": until, "limit": ctx.limit(limit)}
        if item is not None and str(item).strip():
            what = kind or "element"
            found = await {"element": lookup.element, "relationship": lookup.relationship,
                           "view": lookup.view}[what](m["id"], item) if what in ("element", "relationship", "view") \
                else None
            if found is None:
                params.update(kind=what, itemId=int(item) if str(item).isdigit() else None)
            elif found.get("xmiIdentifier"):
                # it stays across a replace of the model; an id may be given again (API 3.11.0)
                params.update(kind=what, xmiIdentifier=found["xmiIdentifier"])
            else:
                params.update(kind=what, itemId=found["id"])
        elif kind:
            params["kind"] = kind
        answer = await api.get(f"/models/{m['id']}/history", **params)
        entries = [_entry(e) for e in answer["items"]]
        return {"model": {"id": m["id"], "name": m["name"]}, "changes": page(entries, answer["total"])}
