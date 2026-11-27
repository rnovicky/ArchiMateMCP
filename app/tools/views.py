"""MCP-6 list_views, get_view; MCP-28 (1.9.0) propose_view and where a view comes from."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from urllib.parse import quote

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from app.api_client import ApiError
from app.links import model_token
from app.lookup import props
from app.tools import READ_ONLY, Context, Limit, ModelRef, Ref, compact, element_summary, page, short

ViewRef = Annotated[Ref, Field(description="The view: its id, XMI identifier or name.")]
Origin = Annotated[Literal["source", "created"] | None, Field(description=(
    "Only the views of the model's source (it came with the imported or linked file; never changed), or only "
    "created views (made in the ArchiMate Browser or through the API)."))]

# The most elements propose_view puts into one diagram (the browser asks before drawing more than 400).
PROPOSE_MAX = 400


def _view_summary(v: dict) -> dict[str, Any]:
    out = {"id": v["id"], "name": v.get("name"), "viewpoint": v.get("viewpoint"),
           "documentation": short(v.get("documentation"), 150), "origin": v.get("origin", "source")}
    if v.get("origin") == "created":
        out["createdBy"] = v.get("createdBy")
    if v.get("recipe") is not None:
        out["recipe"] = v["recipe"]  # 1.13.0 (API 3.22.0): a recipe, no drawing
    return out


RECIPE_NOTE = ("A recipe (API 3.22.0): no drawing, but how a generated diagram is made (what it draws, its filters "
               "and nesting, as an ArchiMate Browser link). The Browser draws it again from the model whenever it is "
               "opened; diagram_image with this view draws it too.")


def origin_of(v: dict, views_by_xmi: dict[str, dict] | None = None) -> dict[str, Any]:
    """MCP-28 (API 3.15.0): where a view comes from, and for a created view who made it, which view it copies,
    and what the last update from the source took out of it."""
    if v.get("origin") != "created":
        return {"origin": "source"}
    out: dict[str, Any] = {"origin": "created", "createdBy": v.get("createdBy"), "createdAt": v.get("createdAt")}
    if v.get("basedOn"):
        source = (views_by_xmi or {}).get(v["basedOn"])
        out["basedOn"] = {"xmiIdentifier": v["basedOn"], **({"id": source["id"], "name": source.get("name")} if source else {})}
    if v.get("lost"):
        out["lost"] = [{k: x.get(k) for k in ("kind", "type", "name", "xmiIdentifier", "reason")} for x in v["lost"]]
    return out


def _walk(nodes: list[dict], parent: dict | None = None):
    """(node, its parent node) for every node of a view, depth first."""
    for node in nodes:
        yield node, parent
        yield from _walk(node.get("children", []), node)


def register(server: MCPServer, ctx: Context) -> None:
    api, lookup = ctx.api, ctx.lookup

    @server.tool(annotations=READ_ONLY)
    @compact
    async def list_views(
        model: ModelRef = None,
        name: Annotated[str | None, Field(description="Only views whose name contains this text.")] = None,
        element: Annotated[Ref | None, Field(
            description="Only views that show this element (its id, XMI identifier or name).")] = None,
        origin: Origin = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """The views (diagrams) of a model, all of them or those whose name contains a text, or those that
        show an element. Each says where it comes from (origin): the model's source, or created (made in the
        ArchiMate Browser or through the API, with who made it).
        """
        m = await lookup.model(model)
        n = ctx.limit(limit)
        where = {"origin": origin} if origin else {}
        if element:
            e = await lookup.element(m["id"], element)
            found = await api.get(f"/models/{m['id']}/views", elementId=e["id"], limit=n, **where)
            items, total = found["items"], found["total"]
        elif name:
            found = (await api.get(f"/models/{m['id']}/search", q=name, kinds="views", limit=n, **{"in": "name"}))["views"]
            items, total = found["items"], found["total"]
            if origin:  # the search has no such filter
                kept = [v for v in items if v.get("origin", "source") == origin]
                items, total = kept, len(kept) if total == len(items) else total - (len(items) - len(kept))
        else:
            found = await api.get(f"/models/{m['id']}/views", limit=n, **where)
            items, total = found["items"], found["total"]
        return {"model": {"id": m["id"], "name": m["name"]}, "views": page([_view_summary(v) for v in items], total)}

    @server.tool(annotations=READ_ONLY)
    @compact
    async def get_view(view: ViewRef, model: ModelRef = None, limit: Limit = None) -> dict[str, Any]:
        """What a view (diagram) shows: its elements, which of them are drawn inside which (nestedIn), the
        relationships drawn between them, its groups and notes, and its links to other views. No
        coordinates or styles. `origin` says whether it is a view of the model's source (never changed) or a
        created view; a created one also says who made it, which view it copies and what an update of the
        model from its source took out of it (`lost`).
        """
        return await describe_view(ctx, model, view, limit)

    @server.tool(annotations=READ_ONLY)
    @compact
    async def propose_view(
        name: Annotated[str, Field(description="The name the view would have.", min_length=1, max_length=500)],
        elements: Annotated[list[Ref], Field(min_length=1, max_length=PROPOSE_MAX, description=(
            "The elements it shows: ids, XMI identifiers or names."))],
        relationships: Annotated[list[Ref] | None, Field(description=(
            "The relationships it draws (ids or XMI identifiers). Default: every relationship between the "
            "elements. Relationships of other elements are left out."))] = None,
        model: ModelRef = None,
    ) -> dict[str, Any]:
        """Propose a new view: a link that opens these elements as a diagram in the ArchiMate Browser, laid out
        automatically, with the name filled in. Nothing is stored: give the user the link; they arrange the diagram
        there and save it as a view (a created view) if they want it. You cannot lay out or save a view yourself.
        Needs BROWSER_URL. Look the elements up first (search, neighbourhood, subgraph).
        """
        m = await lookup.model(model)
        if not ctx.links:
            raise ToolError("No ArchiMate Browser is configured (BROWSER_URL): a view can only be proposed as a link "
                            "to it. List the elements and relationships for the user instead.")
        chosen: dict[int, dict] = {}
        for ref in elements:
            e = await lookup.element(m["id"], ref)
            chosen.setdefault(e["id"], e)
        found = await api.post(f"/models/{m['id']}/graph/subgraph", {"elementIds": list(chosen)})
        between = {r["id"]: r for r in found["relationships"]}
        warnings: list[str] = []
        hidden: list[dict] = []
        if relationships is not None:
            wanted: set[int] = set()
            for ref in relationships:
                r = await lookup.relationship(m["id"], ref)
                if r["id"] in between:
                    wanted.add(r["id"])
                else:
                    warnings.append(f"Relationship {r.get('name') or r['type']} (id {r['id']}) does not join two of "
                                    "the elements; it is left out.")
            hidden_ids = [i for i in between if i not in wanted]
            hidden = list((await ctx.by_ids(m["id"], "relationships", hidden_ids)).values())
        drawn = [r for i, r in between.items() if i not in {h["id"] for h in hidden}]
        link = await ctx.browser_link(m, ctx.links.explore(list(chosen.values()), hidden), vn=name)
        answer: dict[str, Any] = {
            "model": {"id": m["id"], "name": m["name"]},
            "name": name,
            "elements": page([element_summary(e) for e in chosen.values()]),
            "relationships": page([{"id": r["id"], "type": r["type"], **({"name": r["name"]} if r.get("name") else {})}
                                   for r in drawn]),
            "stored": False,
            "next": ("Give the user the link. In the ArchiMate Browser they arrange the diagram and choose "
                     "\"Save as view…\" (it needs a key that may write); nothing is stored before."),
            **link,
        }
        if warnings:
            answer["warnings"] = warnings
        return answer


async def _describe_recipe(ctx: Context, m: dict, v: dict) -> dict[str, Any]:
    """1.13.0: a recipe has no elements of its own: what it is, its recipe, and the link that draws it."""
    answer: dict[str, Any] = {
        "model": {"id": m["id"], "name": m["name"]},
        "id": v["id"], "xmiIdentifier": v.get("xmiIdentifier"), "name": v.get("name"), "version": v.get("version"),
        **origin_of(v), "documentation": v.get("documentation"), "properties": props(v.get("properties")),
        "recipe": v["recipe"], "note": RECIPE_NOTE,
    }
    if ctx.links:
        answer["browserLink"] = ctx.links.base + "#model=" + quote(model_token(m, await ctx.lookup.models()), safe="-*@:~.") + "&" + v["recipe"]
    # 1.16.0 (API 3.25.0): the recipe as the script of one diagram, to read and change it in the script language
    try:
        as_script = await ctx.api.get(f"/models/{m['id']}/views/{v['id']}/recipe-script")
    except ApiError:
        return answer  # an older API
    answer["script"] = as_script.get("script")
    if as_script.get("gaps"):
        answer["scriptGaps"] = as_script["gaps"]
    if as_script.get("madeBy"):
        answer["madeBy"] = as_script["madeBy"]
        answer["note"] += (f" Made by the recipe script \"{as_script['madeBy']['script']}\": change it there "
                           "(recipe_scripts gives its text), since its next run sets this recipe back.")
    elif as_script.get("script"):
        answer["note"] += " To change it: edit `script`, check it with check_recipe_script (view=…), save it with save_recipe_script."
    return answer


async def describe_view(ctx: Context, model: Ref | None, view: Ref, limit: int | None = None) -> dict[str, Any]:
    """The answer of get_view; also the content of the resource archimate://models/{model}/views/{view}."""
    api, lookup = ctx.api, ctx.lookup
    m = await lookup.model(model)
    v = await lookup.view(m["id"], view)
    if v.get("recipe") is not None:
        return await _describe_recipe(ctx, m, v)
    base = f"/models/{m['id']}/views/{v['id']}"
    content = await api.get(f"{base}/content", include="concepts")
    links = await api.get(f"{base}/links")
    by_xmi = {}
    if v.get("basedOn"):
        views = await api.get(f"/models/{m['id']}/views", origin="source", limit=1000)
        by_xmi = {x["xmiIdentifier"]: x for x in views["items"]}
    n = ctx.limit(limit)

    elements = {e["id"]: element_summary(e) for e in content.get("elements", [])}
    element_of_node = {}
    nested: dict[int, list[int]] = {}
    groups: list[dict[str, Any]] = []
    notes: list[str] = []
    for node, parent in _walk(content["nodes"]):
        if node["type"] == "Element" and node.get("elementRefId") is not None:
            element_of_node[node["id"]] = node["elementRefId"]
            if parent is not None and parent["id"] in element_of_node:
                outer = element_of_node[parent["id"]]
                if outer != node["elementRefId"] and outer not in nested.setdefault(node["elementRefId"], []):
                    nested[node["elementRefId"]].append(outer)
        elif node["type"] == "Container":
            inside = sorted({element_of_node.get(c["id"]) or c.get("elementRefId")
                             for c, _ in _walk(node.get("children", [])) if c.get("elementRefId")})
            groups.append({"name": node.get("label"), "elements": inside})
        elif node["type"] == "Label" and node.get("label") and node.get("viewRefId") is None:
            notes.append(node["label"].strip())

    element_list = []
    for element_id, summary in elements.items():
        if element_id in nested:
            summary = {**summary, "nestedIn": nested[element_id]}
        element_list.append(summary)

    def end(r: dict, side: str) -> dict[str, Any] | None:
        if r.get(f"{side}ElementId") is not None:
            eid = r[f"{side}ElementId"]
            return elements.get(eid, {"id": eid})
        if r.get(f"{side}RelationshipId") is not None:
            return {"id": r[f"{side}RelationshipId"], "isRelationship": True}
        return None

    relationships = [
        {"id": r["id"], "type": r["type"], **({"name": r["name"]} if r.get("name") else {}),
         "source": end(r, "source"), "target": end(r, "target")}
        for r in content.get("relationships", [])
    ]
    return {
        "model": {"id": m["id"], "name": m["name"]},
        "id": v["id"], "xmiIdentifier": v.get("xmiIdentifier"), "name": v.get("name"), "version": v.get("version"),
        **origin_of(v, by_xmi),
        "viewpoint": v.get("viewpoint"), "documentation": v.get("documentation"),
        "properties": props(v.get("properties")),
        "elements": page(element_list[:n], len(element_list)),
        "relationships": page(relationships[:n], len(relationships)),
        "groups": groups,
        "notes": notes,
        "linksTo": [{"viewId": x["targetViewId"], "name": x.get("targetViewName"), "label": x.get("label")}
                    for x in links.get("outgoing", [])],
        "linkedFrom": [{"viewId": x["sourceViewId"], "name": x.get("sourceViewName"), "label": x.get("label")}
                       for x in links.get("incoming", [])],
        **await ctx.browser_link(m, ctx.links.view(v)),
    }
