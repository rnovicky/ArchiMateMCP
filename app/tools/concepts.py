"""MCP-4 get_element, MCP-5 get_relationship."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from app.links import token
from app.lookup import props
from app.tools import READ_ONLY, Context, Limit, ModelRef, Ref, compact, element_summary, page

ElementRef = Annotated[Ref, Field(description="The element: its id, XMI identifier or name.")]
RelationshipRef = Annotated[Ref, Field(description="The relationship: its id or XMI identifier.")]


def _link(entry: dict) -> dict[str, Any]:
    """One relationship of an element, with what is at its other end."""
    r = entry["relationship"]
    out: dict[str, Any] = {"relationshipId": r["id"], "type": r["type"]}
    if r.get("name"):
        out["name"] = r["name"]
    for key in ("accessType", "influenceModifier"):
        if r.get(key):
            out[key] = r[key]
    if entry.get("element"):
        out["element"] = element_summary(entry["element"])
    elif entry.get("otherRelationship"):
        other = entry["otherRelationship"]
        out["relationship"] = {"id": other["id"], "type": other["type"], "name": other.get("name")}
    return out


def register(server: MCPServer, ctx: Context) -> None:
    api, lookup = ctx.api, ctx.lookup

    @server.tool(annotations=READ_ONLY)
    @compact
    async def get_element(element: ElementRef, model: ModelRef = None, limit: Limit = None) -> dict[str, Any]:
        """One element: its documentation and properties, the folders it is filed in, its relationships
        (outgoing: the element is the source; incoming: it is the target) with the element at the other
        end, and the views that show it.
        """
        return await describe_element(ctx, model, element, limit)

    @server.tool(annotations=READ_ONLY)
    @compact
    async def get_relationship(relationship: RelationshipRef, model: ModelRef = None) -> dict[str, Any]:
        """One relationship: its type, name, documentation and properties, its source and target, and the
        views that show it. get_element lists an element's relationships with their ids.
        """
        m = await lookup.model(model)
        r = await lookup.relationship(m["id"], relationship)
        base = f"/models/{m['id']}"

        async def end(side: str) -> dict[str, Any] | None:
            if r.get(f"{side}ElementId"):
                return element_summary(await api.get(f"{base}/elements/{r[f'{side}ElementId']}"))
            if r.get(f"{side}RelationshipId"):
                other = await api.get(f"{base}/relationships/{r[f'{side}RelationshipId']}")
                return {"id": other["id"], "type": other["type"], "name": other.get("name"), "isRelationship": True}
            return None

        views = await api.get(f"{base}/relationships/{r['id']}/views", limit=ctx.settings.max_results)
        answer: dict[str, Any] = {
            "model": {"id": m["id"], "name": m["name"]},
            "id": r["id"], "xmiIdentifier": r.get("xmiIdentifier"), "type": r["type"], "name": r.get("name"),
            "version": r.get("version"), "documentation": r.get("documentation"),
            "properties": props(r.get("properties")),
            "source": await end("source"), "target": await end("target"),
            "views": page([{"id": u["view"]["id"], "name": u["view"].get("name")} for u in views["items"]], views["total"]),
        }
        for key in ("accessType", "influenceModifier", "isDirected"):
            if r.get(key) is not None:
                answer[key] = r[key]
        return answer


async def describe_element(ctx: Context, model: Ref | None, element: Ref, limit: int | None = None) -> dict[str, Any]:
    """The answer of get_element; also the content of the resource archimate://models/{model}/elements/{element}."""
    api, lookup = ctx.api, ctx.lookup
    m = await lookup.model(model)
    e = await lookup.element(m["id"], element)
    base = f"/models/{m['id']}/elements/{e['id']}"
    n = ctx.limit(limit)
    neighbours = await api.get(f"{base}/neighbours")
    folders = await api.get(f"{base}/folders")
    views = await api.get(f"{base}/views", limit=n)
    outgoing, incoming = neighbours.get("outgoing", []), neighbours.get("incoming", [])
    return {
        "model": {"id": m["id"], "name": m["name"]},
        "id": e["id"], "xmiIdentifier": e.get("xmiIdentifier"), "name": e.get("name"), "type": e["type"],
        "version": e.get("version"), "documentation": e.get("documentation"),
        "properties": props(e.get("properties")),
        "folders": ["/".join(f.get("label") or "" for f in path) for path in folders],
        "outgoing": page([_link(x) for x in outgoing[:n]], len(outgoing)),
        "incoming": page([_link(x) for x in incoming[:n]], len(incoming)),
        "views": page([{"id": u["view"]["id"], "name": u["view"].get("name")} for u in views["items"]], views["total"]),
        **await ctx.browser_link(m, None, element=token(e)),
    }
