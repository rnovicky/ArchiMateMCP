"""MCP-8 impact_analysis, MCP-9 find_paths, MCP-10 neighbourhood and subgraph, MCP-11 browser_link."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from app.links import folder_token, token
from app.tools import READ_ONLY, Context, Limit, ModelRef, Ref, compact, element_summary, page
from app.tools.search import Layer

ElementRefs = Annotated[list[Ref], Field(
    description="Elements: each its id, XMI identifier or name.", min_length=1)]
RelationshipTypes = Annotated[list[str] | None, Field(
    description="Only these relationship types, e.g. Serving, Flow; default: see the tool.")]
ElementTypes = Annotated[list[str] | None, Field(description="Only elements of these types are reached.")]
Layers = Annotated[list[Layer] | None, Field(description="Only elements of these layers are reached.")]


def _relationship(r: dict, elements: dict[int, dict]) -> dict[str, Any]:
    """A relationship with its ends named, where the ends are among `elements`."""
    def end(side: str) -> dict[str, Any] | None:
        if r.get(f"{side}ElementId") is not None:
            eid = r[f"{side}ElementId"]
            return elements.get(eid) or {"id": eid}
        if r.get(f"{side}RelationshipId") is not None:
            return {"id": r[f"{side}RelationshipId"], "isRelationship": True}
        return None
    out: dict[str, Any] = {"id": r["id"], "type": r["type"]}
    if r.get("name"):
        out["name"] = r["name"]
    out.update(source=end("source"), target=end("target"))
    return out


def register(server: MCPServer, ctx: Context) -> None:
    api, lookup = ctx.api, ctx.lookup

    async def elements_of(model_id: int, refs: list[Ref]) -> list[dict]:
        found: list[dict] = []
        for ref in refs:
            e = await lookup.element(model_id, ref)
            if all(x["id"] != e["id"] for x in found):
                found.append(e)
        return found

    @server.tool(annotations=READ_ONLY)
    @compact
    async def impact_analysis(
        elements: ElementRefs,
        model: ModelRef = None,
        direction: Annotated[Literal["impact", "dependencies"], Field(
            description="impact: what a change of the elements affects; dependencies: what they depend on.")] = "impact",
        max_depth: Annotated[int, Field(description="How many steps away, 1 to 10.", ge=1, le=10)] = 3,
        relationship_types: RelationshipTypes = None,
        element_types: ElementTypes = None,
        layers: Layers = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """What a change of elements affects, or what they depend on, level by level.

        Follows relationships in the direction a change propagates: by default Serving, Realization,
        Assignment, Flow and Triggering from source to target; Composition, Aggregation and Access from
        target to source (the archimate://metamodel resource lists the rules). Each element reached says
        from which element and over which relationship it was reached.
        """
        m = await lookup.model(model)
        starts = await elements_of(m["id"], elements)
        body = {"start": [e["id"] for e in starts], "direction": direction, "maxDepth": max_depth,
                "relationshipTypes": relationship_types, "elementTypes": element_types, "layers": layers}
        result = await api.post(f"/models/{m['id']}/graph/impact", {k: v for k, v in body.items() if v is not None})
        n = ctx.limit(limit)
        reached = result["results"]
        shown = reached[:n]
        names = {e["id"]: element_summary(e) for e in starts}
        names.update({i: element_summary(e) for i, e in (await ctx.by_ids(
            m["id"], "elements", [r["elementId"] for r in shown] + [r["fromElementId"] for r in shown])).items()})
        via = await ctx.by_ids(m["id"], "relationships", [r["viaRelationshipId"] for r in shown])
        levels: dict[int, list] = {}
        for r in shown:
            relationship = via.get(r["viaRelationshipId"], {})
            levels.setdefault(r["level"], []).append({
                **names.get(r["elementId"], {"id": r["elementId"]}),
                "from": r["fromElementId"],
                "via": {"relationshipId": r["viaRelationshipId"], "type": relationship.get("type")},
            })
        answer: dict[str, Any] = {
            "model": {"id": m["id"], "name": m["name"]},
            "direction": direction,
            "start": [element_summary(e) for e in starts],
            "reached": len(reached),
            "maxLevel": result["maxLevel"],
            "levels": [{"level": level, "elements": items} for level, items in sorted(levels.items())],
        }
        if len(reached) > len(shown):
            answer["truncated"] = True
            answer["shown"] = len(shown)
        if result.get("truncated"):
            answer["moreBeyondMaxDepth"] = True
        answer.update(await ctx.browser_link(m, ctx.links.impact(starts, direction, max_depth, relationship_types)))
        return answer

    @server.tool(annotations=READ_ONLY)
    @compact
    async def find_paths(
        source: Annotated[Ref, Field(description="The element the paths start at: id, XMI identifier or name.")],
        target: Annotated[Ref, Field(description="The element the paths end at: id, XMI identifier or name.")],
        model: ModelRef = None,
        max_length: Annotated[int, Field(description="Longest path, in relationships (1 to 10).", ge=1, le=10)] = 6,
        count: Annotated[int, Field(description="How many paths, the shortest first (1 to 10).", ge=1, le=10)] = 3,
        directed: Annotated[bool, Field(
            description="Follow relationships from source to target only; default: either way.")] = False,
        relationship_types: RelationshipTypes = None,
    ) -> dict[str, Any]:
        """How two elements are connected: the shortest paths between them, each as a readable chain
        ("Web Shop -Flow-> Kafka -Flow-> ERP") and as steps. No path gives an empty list.
        """
        m = await lookup.model(model)
        a = await lookup.element(m["id"], source)
        b = await lookup.element(m["id"], target)
        if a["id"] == b["id"]:
            raise ToolError("The source and the target are the same element.")
        result = await api.get(f"/models/{m['id']}/graph/paths", **{
            "from": a["id"], "to": b["id"], "maxLength": max_length, "k": count,
            "direction": "directed" if directed else "any",
            "relationshipTypes": ",".join(relationship_types) if relationship_types else None})
        steps = [s for p in result["paths"] for s in p["steps"]]
        elements = {i: element_summary(e) for i, e in (await ctx.by_ids(
            m["id"], "elements", [s.get("elementId") for s in steps])).items()}
        relationships = await ctx.by_ids(m["id"], "relationships", [s.get("relationshipId") for s in steps])
        paths = []
        for p in result["paths"]:
            text, out, previous = [], [], None
            for s in p["steps"]:
                if "elementId" in s:
                    e = elements.get(s["elementId"], {"id": s["elementId"]})
                    out.append(e)
                    text.append(e.get("name") or f"#{e['id']}")
                    previous = s["elementId"]
                else:
                    r = relationships.get(s["relationshipId"], {"id": s["relationshipId"]})
                    forward = r.get("sourceElementId") == previous
                    out.append({"relationshipId": r["id"], "type": r.get("type"),
                                "direction": "forward" if forward else "backward"})
                    text.append(f"-{r.get('type')}->" if forward else f"<-{r.get('type')}-")
            paths.append({"length": p["length"], "text": " ".join(text), "steps": out})
        answer: dict[str, Any] = {"model": {"id": m["id"], "name": m["name"]},
                                  "source": element_summary(a), "target": element_summary(b), "paths": paths}
        if result.get("truncated"):
            answer["searchCutShort"] = True
        answer.update(await ctx.browser_link(m, ctx.links.paths(a, b)))
        return answer

    @server.tool(annotations=READ_ONLY)
    @compact
    async def neighbourhood(
        elements: ElementRefs,
        model: ModelRef = None,
        depth: Annotated[int, Field(description="How many relationships away (0 to 5).", ge=0, le=5)] = 1,
        direction: Annotated[Literal["both", "out", "in"], Field(
            description="out: follow relationships from source to target; in: the other way; both.")] = "both",
        incoming_types: Annotated[list[str] | None, Field(description=(
            "Only these relationship types are followed against their direction (target to source), at every "
            "step; needs direction both or in. Default: every type. API 3.24.0."))] = None,
        outgoing_types: Annotated[list[str] | None, Field(description=(
            "Only these relationship types are followed along their direction (source to target), at every step; "
            "needs direction both or out. Default: every type. E.g. every incoming relationship but outgoing only "
            "Serving and Realization. API 3.24.0."))] = None,
        relationship_types: RelationshipTypes = None,
        element_types: ElementTypes = None,
        layers: Layers = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """The elements around some elements, each with its distance, and the relationships among them.
        Junctions are passed through. Default: every relationship type. incoming_types and outgoing_types narrow
        which relationships are followed in each direction (not which are returned among the elements reached);
        relationship_types narrows both.
        """
        m = await lookup.model(model)
        seeds = await elements_of(m["id"], elements)
        if incoming_types is not None and direction == "out":
            raise ToolError("incoming_types needs direction both or in.")
        if outgoing_types is not None and direction == "in":
            raise ToolError("outgoing_types needs direction both or out.")
        body = {"seeds": [e["id"] for e in seeds], "depth": depth, "direction": direction,
                "incomingTypes": incoming_types, "outgoingTypes": outgoing_types,
                "relationshipTypes": relationship_types, "elementTypes": element_types, "layers": layers}
        result = await api.post(f"/models/{m['id']}/graph/neighbourhood", {k: v for k, v in body.items() if v is not None})
        n = ctx.limit(limit)
        found = {e["id"]: element_summary(e) for e in result["elements"]}
        items = [{**found[e["id"]], "distance": e["distance"]} for e in result["elements"]]
        relationships = [_relationship(r, found) for r in result["relationships"]]
        answer: dict[str, Any] = {
            "model": {"id": m["id"], "name": m["name"]},
            "seeds": [element_summary(e) for e in seeds],
            "elements": page(items[:n], len(items)),
            "relationships": page(relationships[:n], len(relationships)),
        }
        if result.get("truncated"):
            answer["cutByServer"] = True
        diagram = (ctx.links.neighbourhood(seeds, depth, direction, incoming_types, outgoing_types)
                   if not (relationship_types or element_types or layers) else None)
        answer.update(await ctx.browser_link(m, diagram))
        return answer

    @server.tool(annotations=READ_ONLY)
    @compact
    async def subgraph(
        model: ModelRef = None,
        elements: Annotated[list[Ref] | None, Field(description="These elements (ids, XMI identifiers or names).")] = None,
        folder: Annotated[Ref | None, Field(description="Everything filed in this folder and below (id or path).")] = None,
        view: Annotated[Ref | None, Field(description="The elements this view shows (id, XMI identifier or name).")] = None,
        element_type: Annotated[str | None, Field(description="Every element of this type.")] = None,
        layer: Annotated[Layer | None, Field(description="Every element of this layer.")] = None,
        relationship_types: RelationshipTypes = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """A set of elements and the relationships among them: the given elements, a folder's, a view's,
        every element of a type or of a layer. Give exactly one of these.
        """
        m = await lookup.model(model)
        given = [x for x in (elements, folder, view, element_type, layer) if x]
        if len(given) != 1:
            raise ToolError("Give exactly one of elements, folder, view, element_type and layer.")
        body: dict[str, Any] = {}
        diagram = None
        if elements:
            chosen = await elements_of(m["id"], elements)
            body["elementIds"] = [e["id"] for e in chosen]
            diagram = ctx.links.elements(chosen)
        elif folder:
            node, _ = await lookup.folder(m["id"], folder)
            body["folderId"] = node["id"]
            diagram = ctx.links.folder(folder_token(await lookup.folder_tree(m["id"]), node["id"]))
        elif view:
            v = await lookup.view(m["id"], view)
            body["viewId"] = v["id"]
            diagram = ctx.links.view(v)
        elif element_type:
            body["elementType"] = element_type
            diagram = ctx.links.element_type(element_type)
        else:
            body["layer"] = layer
            diagram = ctx.links.layer(layer)
        if relationship_types:
            body["relationshipTypes"] = relationship_types
        result = await api.post(f"/models/{m['id']}/graph/subgraph", body)
        n = ctx.limit(limit)
        found = {e["id"]: element_summary(e) for e in result["elements"]}
        relationships = [_relationship(r, found) for r in result["relationships"]]
        answer: dict[str, Any] = {
            "model": {"id": m["id"], "name": m["name"]},
            "elements": page(list(found.values())[:n], len(found)),
            "relationships": page(relationships[:n], len(relationships)),
        }
        if result.get("truncated"):
            answer["cutByServer"] = True
        answer.update(await ctx.browser_link(m, None if relationship_types else diagram))
        return answer

    @server.tool(annotations=READ_ONLY)
    @compact
    async def browser_link(
        model: ModelRef = None,
        elements: Annotated[list[Ref] | None, Field(
            description="A diagram of these elements (ids, XMI identifiers or names).")] = None,
        view: Annotated[Ref | None, Field(description="This view (id, XMI identifier or name).")] = None,
        folder: Annotated[Ref | None, Field(description="A diagram of everything in this folder (id or path).")] = None,
        select: Annotated[Ref | None, Field(
            description="An element to select in the browser's tree and details (id, XMI identifier or name).")] = None,
    ) -> dict[str, Any]:
        """A link that opens a diagram in the ArchiMate Browser, for the user to click: of given elements,
        of a view, or of a folder; or the model with an element selected. Other tools add such links to their
        answers by themselves (browserLink). Needs BROWSER_URL in the server's settings.
        """
        if not ctx.links:
            raise ToolError("The server has no BROWSER_URL, so it cannot make links to the ArchiMate Browser.")
        m = await lookup.model(model)
        given = [x for x in (elements, view, folder) if x]
        if len(given) > 1:
            raise ToolError("Give at most one of elements, view and folder.")
        diagram = None
        if elements:
            diagram = ctx.links.elements(await elements_of(m["id"], elements))
        elif view:
            diagram = ctx.links.view(await lookup.view(m["id"], view))
        elif folder:
            node, _ = await lookup.folder(m["id"], folder)
            diagram = ctx.links.folder(folder_token(await lookup.folder_tree(m["id"]), node["id"]))
        selection = {}
        if select:
            selection["element"] = token(await lookup.element(m["id"], select))
        return {"model": {"id": m["id"], "name": m["name"]}, **await ctx.browser_link(m, diagram, **selection)}
