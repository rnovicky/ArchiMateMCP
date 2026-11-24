"""MCP-18 model_quality, MCP-19 relationship_matrix, MCP-20 landscape: the API's reports (3.6.0)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from app.links import folder_token
from app.tools import READ_ONLY, Context, Limit, ModelRef, Ref, compact, element_summary, page
from app.tools.search import Layer

Check = Literal["elementsInNoView", "elementsWithoutRelationships", "unfiledElements", "unfiledRelationships",
                "unfiledViews", "duplicateNames", "emptyViews", "emptyLabels", "relationshipsNotAllowed"]
Direction = Literal["out", "in", "any"]


class ElementSetArg(BaseModel):
    """A set of elements. Give one of elements, element_type, layer, folder and view; element_types and
    property narrow it (element_types alone names a set too). Junctions are never members."""

    elements: list[Ref] | None = Field(None, description="These elements: ids, XMI identifiers or names.")
    element_type: str | None = Field(None, description="Every element of this type, e.g. ApplicationComponent.")
    layer: Layer | None = Field(None, description="Every element of this layer.")
    folder: Ref | None = Field(None, description="Everything filed in this folder and below (id or path).")
    view: Ref | None = Field(None, description="The elements this view shows (id, XMI identifier or name).")
    element_types: list[str] | None = Field(None, description="Only elements of these types.")
    property: str | None = Field(None, description="Only elements that have this property...")
    property_value: str | None = Field(None, description="...with this value (without regard to case).")


class Step(BaseModel):
    types: list[str] | None = Field(None, description="Relationship types of this step; none: all.")
    direction: Direction = Field("any", description="out: from source to target, walking from the row towards "
                                                    "the column; in: the reverse; any: either.")


class NestingRule(BaseModel):
    type: str = Field(description="A relationship type, e.g. Composition, Aggregation, Realization.")
    direction: Literal["out", "in"] = Field("out", description="out: the source is the parent (Composition, "
                                                               "Aggregation); in: the target is the parent (e.g. "
                                                               "Realization: the applications under a capability).")


def _arrow(rel_type: str | None, forward: bool) -> str:
    return f"-{rel_type}->" if forward else f"<-{rel_type}-"


def register(server: MCPServer, ctx: Context) -> None:
    api, lookup = ctx.api, ctx.lookup

    async def element_set(model_id: int, spec: ElementSetArg) -> dict[str, Any]:
        """The API's element set, with the references resolved to ids."""
        body: dict[str, Any] = {}
        given = [x for x in (spec.elements, spec.element_type, spec.layer, spec.folder, spec.view) if x]
        if len(given) > 1 or (not given and not spec.element_types):
            raise ToolError("A set needs exactly one of elements, element_type, layer, folder and view "
                            "(or element_types alone).")
        if spec.elements:
            ids = []
            for ref in spec.elements:
                ids.append((await lookup.element(model_id, ref))["id"])
            body["elementIds"] = list(dict.fromkeys(ids))
        elif spec.element_type:
            body["elementType"] = spec.element_type
        elif spec.layer:
            body["layer"] = spec.layer
        elif spec.folder:
            body["folderId"] = (await lookup.folder(model_id, spec.folder))[0]["id"]
        elif spec.view:
            body["viewId"] = (await lookup.view(model_id, spec.view))["id"]
        if spec.element_types:
            body["elementTypes"] = spec.element_types
        if spec.property:
            body["property"] = {"name": spec.property, **({"value": spec.property_value} if spec.property_value else {})}
        return body

    @server.tool(annotations=READ_ONLY)
    @compact
    async def model_quality(
        model: ModelRef = None,
        checks: Annotated[list[Check] | None, Field(description="Which checks; default: all.")] = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """What in a model is probably unfinished or wrong: elements in no view, elements without
        relationships, elements, relationships and views filed in no folder, elements of one type with the
        same name, views without nodes, empty labels (drill-down links whose view was deleted), and
        relationships whose type ArchiMate does not allow between the types of their ends (see
        allowed_relationships for what would be allowed).

        Each check gives its total and the first items. A finding is not an error by itself: an element in
        no view can be on purpose. Use it for a model review, with model_overview for context.
        """
        m = await lookup.model(model)
        n = ctx.limit(limit)
        params = {"limit": n}
        if checks:
            params["checks"] = ",".join(checks)
        report = await api.get(f"/models/{m['id']}/analysis/quality", **params)
        answer: dict[str, Any] = {"model": {"id": m["id"], "name": m["name"]}, "checks": {}}
        for name, group in report["checks"].items():
            if name == "duplicateNames":
                items = [{"type": g["type"], "name": g["name"], "elements": [e["id"] for e in g["elements"]]}
                         for g in group["items"]]
            elif name == "emptyLabels":
                items = [{"nodeId": x["nodeId"], "view": x["view"]} for x in group["items"]]
            elif name in ("unfiledViews", "emptyViews"):
                items = [{"id": v["id"], "name": v.get("name")} for v in group["items"]]
            elif name == "unfiledRelationships":
                items = [{"id": r["id"], "type": r["type"], "name": r.get("name")} for r in group["items"]]
            elif name == "relationshipsNotAllowed":
                items = [{"id": r["id"], "type": r["type"], "name": r.get("name"), "sourceType": r["sourceType"],
                          "targetType": r["targetType"], "source": r.get("sourceElementId") or r.get("sourceRelationshipId"),
                          "target": r.get("targetElementId") or r.get("targetRelationshipId")} for r in group["items"]]
            else:
                items = [element_summary(e) for e in group["items"]]
            answer["checks"][name] = page(items, group["total"])
        answer["summary"] = {name: group["total"] for name, group in report["checks"].items()}
        return answer

    @server.tool(annotations=READ_ONLY)
    @compact
    async def relationship_matrix(
        rows: Annotated[ElementSetArg, Field(description="The row elements.")],
        columns: Annotated[ElementSetArg, Field(description="The column elements.")],
        model: ModelRef = None,
        relationship_types: Annotated[list[str] | None, Field(
            description="Direct relationships of these types (without path); default: all.")] = None,
        direction: Annotated[Direction, Field(description="Direct: out = row is the source.")] = "any",
        path: Annotated[list[Step] | None, Field(
            description="Instead of direct relationships: a pattern of 1 to 3 steps from the row to the column, "
                        "e.g. Realization out, then Serving out.", max_length=3)] = None,
        intermediate_types: Annotated[list[list[str] | None] | None, Field(
            description="With path: the element types allowed at each intermediate position (steps - 1 "
                        "entries; null for any), e.g. [[\"ApplicationService\"]].")] = None,
        include_empty: Annotated[bool, Field(description="Also rows and columns without any connection.")] = False,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """Which elements of one set connect to which of another: directly, or along a path pattern such as
        components that realize a service that serves a process. Each connected pair (cell) gives its count
        and its paths as readable chains ("ERP -Realization-> Order API -Serving-> Web Shop").

        Typical questions: which applications support which processes; which nodes host which applications.
        Junctions are passed through; paths never repeat an element.
        """
        m = await lookup.model(model)
        body: dict[str, Any] = {"rows": await element_set(m["id"], rows), "columns": await element_set(m["id"], columns),
                                "includeEmpty": include_empty}
        if path:
            body["via"] = {"path": [s.model_dump(exclude_none=True) for s in path]}
            if intermediate_types is not None:
                body["via"]["intermediateTypes"] = intermediate_types
        else:
            body["via"] = {"direction": direction, **({"types": relationship_types} if relationship_types else {})}
        result = await api.post(f"/models/{m['id']}/graph/matrix", body)
        n = ctx.limit(limit)
        cells = result["cells"][:n]
        names = {e["id"]: e for e in result["rows"] + result["columns"]}
        rel_ids = [r for c in cells for p in c.get("paths", []) for r in p["relationshipIds"]]
        middle_ids = [i for c in cells for p in c.get("paths", []) for i in p["intermediateIds"]]
        rels = await ctx.by_ids(m["id"], "relationships", rel_ids)
        middles = {i: element_summary(e) for i, e in (await ctx.by_ids(m["id"], "elements", middle_ids)).items()}

        def label(element_id: int | None) -> str:
            if element_id in middles:
                return middles[element_id].get("name") or f"#{element_id}"
            if element_id in names:
                return names[element_id].get("name") or f"#{element_id}"
            return "(junction)" if element_id is not None else "(relationship)"

        def chain(row: int, column: int, p: dict) -> str:
            """The path as text: each relationship with the element at its other end."""
            text, previous = [label(row)], row
            for rel_id in p["relationshipIds"]:
                r = rels.get(rel_id, {})
                forward = r.get("sourceElementId") == previous
                other = r.get("targetElementId") if forward else r.get("sourceElementId")
                text += [_arrow(r.get("type"), forward), label(other)]
                previous = other
            if previous != column:  # reached through the ends of a relationship (rule 2)
                text.append(f"... {label(column)}")
            return " ".join(text)

        out_cells = [{
            "row": names[c["row"]].get("name"), "column": names[c["column"]].get("name"),
            "rowId": c["row"], "columnId": c["column"], "count": c["count"],
            "paths": [chain(c["row"], c["column"], p) for p in c.get("paths", [])[:5]],
        } for c in cells]
        answer: dict[str, Any] = {
            "model": {"id": m["id"], "name": m["name"]},
            "rows": len(result["rows"]), "columns": len(result["columns"]),
            "cells": page(out_cells, len(result["cells"])),
            "totals": result["totals"],
        }
        if result.get("truncated"):
            answer["cutByServer"] = True
        if result["rows"] or result["columns"]:
            both = {e["id"]: e for e in result["rows"] + result["columns"]}
            if len(both) <= 200:
                answer.update(await ctx.browser_link(m, ctx.links.elements(list(both.values()))))
        return answer

    @server.tool(annotations=READ_ONLY)
    @compact
    async def landscape(
        roots: Annotated[ElementSetArg, Field(description="The root elements, e.g. element_type Capability.")],
        model: ModelRef = None,
        nesting: Annotated[list[NestingRule] | None, Field(
            description="Which relationships place an element below another, in order of preference; default: "
                        "Composition out, Aggregation out.")] = None,
        child_types: Annotated[list[str] | None, Field(description="Only elements of these types below the roots.")] = None,
        max_depth: Annotated[int, Field(description="Levels below the roots, 1 to 10.", ge=1, le=10)] = 3,
        properties: Annotated[list[str] | None, Field(
            description="Property values to show per element, e.g. [\"Lifecycle\", \"Owner\"].")] = None,
        lang: Annotated[str | None, Field(description="Preferred language of property values.")] = None,
        limit: Annotated[int | None, Field(description="Most elements in the answer; default MAX_RESULTS x 5.", ge=1)] = None,
    ) -> dict[str, Any]:
        """A landscape map as a tree: the elements below root elements along nesting relationships, e.g. a
        capability map with sub-capabilities, or capabilities with the applications that realize them
        (nesting: Composition out, then Realization in). Every element appears once, under its preferred
        parent; other parent links are listed. Property values per element, and the values found, for a
        legend.
        """
        m = await lookup.model(model)
        body: dict[str, Any] = {"roots": await element_set(m["id"], roots), "maxDepth": max_depth,
                                "properties": properties or [], "counts": True}
        if nesting:
            body["nesting"] = [r.model_dump() for r in nesting]
        if child_types:
            body["childTypes"] = child_types
        if lang:
            body["lang"] = lang
        result = await api.post(f"/models/{m['id']}/graph/hierarchy", body)
        budget = limit or ctx.settings.max_results * 5
        shown = 0
        cut = False

        def node(n: dict) -> dict[str, Any] | None:
            nonlocal shown, cut
            if shown >= budget:
                cut = True
                return None
            shown += 1
            item: dict[str, Any] = {"id": n["id"], "name": n.get("name"), "type": n["type"]}
            if n.get("properties"):
                item["properties"] = n["properties"]
            if n.get("via"):
                item["via"] = n["via"]["type"]
            kids = [k for k in (node(c) for c in n.get("children", [])) if k]
            if kids:
                item["children"] = kids
            if n.get("descendants") and len(kids) < len(n.get("children", [])):
                item["descendants"] = n["descendants"]
            if n.get("more"):
                item["more"] = True
            return item

        tree = [t for t in (node(r) for r in result["roots"]) if t]
        answer: dict[str, Any] = {
            "model": {"id": m["id"], "name": m["name"]},
            "roots": tree,
            "elements": shown,
            "otherParents": result["otherParents"][: ctx.limit(None)],
        }
        if result.get("propertyValues"):
            answer["propertyValues"] = result["propertyValues"]
        if cut:
            answer["truncated"] = True
        if result.get("truncated"):
            answer["cutByServer"] = True
        if roots.folder and not cut:
            node0, _ = await lookup.folder(m["id"], roots.folder)
            answer.update(await ctx.browser_link(m, ctx.links.folder(folder_token(await lookup.folder_tree(m["id"]), node0["id"]))))
        return answer
