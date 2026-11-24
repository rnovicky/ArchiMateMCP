"""MCP-3 search."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from app.tools import READ_ONLY, Context, Limit, ModelRef, compact, element_summary, page, short

Kind = Literal["elements", "relationships", "views"]
Layer = Literal["Strategy", "Business", "Application", "Technology", "Physical", "Motivation",
                "ImplementationMigration", "Other"]
SearchField = Literal["name", "documentation", "properties"]


def _csv(values: list[str] | None) -> str | None:
    return ",".join(values) if values else None


def register(server: MCPServer, ctx: Context) -> None:
    api, lookup = ctx.api, ctx.lookup

    @server.tool(annotations=READ_ONLY)
    @compact
    async def search(
        model: ModelRef = None,
        query: Annotated[str, Field(description="Text to look for; may be empty when a filter is given.")] = "",
        kinds: Annotated[list[Kind] | None, Field(
            description="What to look for; default: elements, relationships and views.")] = None,
        element_types: Annotated[list[str] | None, Field(
            description="ArchiMate element types without spaces, e.g. ApplicationComponent, BusinessProcess.")] = None,
        layers: Annotated[list[Layer] | None, Field(description="Only elements of these layers.")] = None,
        relationship_types: Annotated[list[str] | None, Field(
            description="ArchiMate relationship types, e.g. Serving, Realization, Flow.")] = None,
        fields: Annotated[list[SearchField] | None, Field(
            description="Where the text is looked for; default: the name only.")] = None,
        property: Annotated[str | None, Field(
            description="Only items that have this property (model_overview lists the names).")] = None,
        property_value: Annotated[str | None, Field(
            description="With property: only items whose value of it is this (without regard to case).")] = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """Find elements, relationships and views by text, type, layer or property value.

        Results are ranked: a name equal to the text first, then names that start with it, then the rest.
        Ids in the answer are what get_element, get_relationship and get_view take.
        """
        m = await lookup.model(model)
        n = ctx.limit(limit)
        found = await api.get(
            f"/models/{m['id']}/search", q=query, kinds=_csv(kinds or ["elements", "relationships", "views"]), elementTypes=_csv(element_types),
            layers=_csv(layers), relationshipTypes=_csv(relationship_types), property=property,
            propertyValue=property_value, limit=n, **{"in": _csv(fields)},
        )
        answer: dict[str, Any] = {"model": {"id": m["id"], "name": m["name"]}}
        if "elements" in found:
            group = found["elements"]
            answer["elements"] = page([
                {**element_summary(e), "documentation": short(e.get("documentation"), 150),
                 **({"matchedIn": fields} if (fields := (e.get("match") or {}).get("fields")) else {})}
                for e in group["items"]
            ], group["total"])
        if "relationships" in found:
            group = found["relationships"]
            ends = await _ends(api, m["id"], group["items"])
            answer["relationships"] = page([
                {"id": r["id"], "type": r["type"], "name": r.get("name"),
                 "source": ends.get(("e", r.get("sourceElementId")), ends.get(("r", r.get("sourceRelationshipId")))),
                 "target": ends.get(("e", r.get("targetElementId")), ends.get(("r", r.get("targetRelationshipId"))))}
                for r in group["items"]
            ], group["total"])
        if "views" in found:
            group = found["views"]
            answer["views"] = page([
                {"id": v["id"], "name": v.get("name"), "viewpoint": v.get("viewpoint"),
                 "documentation": short(v.get("documentation"), 150)}
                for v in group["items"]
            ], group["total"])
        return answer


async def _ends(api, model_id: int, relationships: list[dict]) -> dict[tuple[str, int], dict]:
    """The ends of relationships as summaries, keyed ("e", element id) or ("r", relationship id)."""
    element_ids = {r[k] for r in relationships for k in ("sourceElementId", "targetElementId") if r.get(k)}
    relationship_ids = {r[k] for r in relationships for k in ("sourceRelationshipId", "targetRelationshipId") if r.get(k)}
    ends: dict[tuple[str, int], dict] = {}
    if element_ids:
        items = (await api.get(f"/models/{model_id}/elements", ids=",".join(map(str, sorted(element_ids))),
                               limit=1000))["items"]
        ends.update({("e", e["id"]): element_summary(e) for e in items})
    if relationship_ids:
        items = (await api.get(f"/models/{model_id}/relationships", ids=",".join(map(str, sorted(relationship_ids))),
                               limit=1000))["items"]
        ends.update({("r", r["id"]): {"id": r["id"], "type": r["type"], "name": r.get("name"), "isRelationship": True}
                     for r in items})
    return ends
