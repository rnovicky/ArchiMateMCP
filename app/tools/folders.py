"""MCP-7 browse_folders."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from app.links import folder_token
from app.tools import READ_ONLY, Context, Limit, ModelRef, Ref, compact, element_summary, page


def _folder(node: dict) -> dict[str, Any]:
    return {"id": node["id"], "name": node.get("label"), **node.get("counts", {})}


def register(server: MCPServer, ctx: Context) -> None:
    api, lookup = ctx.api, ctx.lookup

    @server.tool(annotations=READ_ONLY)
    @compact
    async def browse_folders(
        model: ModelRef = None,
        folder: Annotated[Ref | None, Field(
            description="The folder: its id, its path with / between the names (\"Business/Processes\"), or a "
                        "name only one folder has. Leave it out for the top level.")] = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """The folder tree of a model, one level at a time: a folder's sub-folders, with how much each holds at
        any depth, and the elements, relationships and views filed directly in it (by name).
        """
        m = await lookup.model(model)
        answer: dict[str, Any] = {"model": {"id": m["id"], "name": m["name"]}}
        if not folder:
            tree = await lookup.folder_tree(m["id"])
            answer["folders"] = [_folder(f) for f in tree]
            return answer
        node, path = await lookup.folder(m["id"], folder)
        n = ctx.limit(limit)
        contents = await api.get(f"/models/{m['id']}/organizations/{node['id']}/contents",
                                 recursive="false", order="name", limit=n)
        answer.update({
            "folder": {"id": node["id"], "path": "/".join(path), "version": node.get("version"), **node.get("counts", {})},
            "folders": [_folder(f) for f in node.get("children", [])],
            "elements": page([element_summary(e) for e in contents["elements"]["items"]], contents["elements"]["total"]),
            "relationships": page([{"id": r["id"], "type": r["type"], "name": r.get("name")}
                                   for r in contents["relationships"]["items"]], contents["relationships"]["total"]),
            "views": page([{"id": v["id"], "name": v.get("name")} for v in contents["views"]["items"]],
                          contents["views"]["total"]),
        })
        answer.update(await ctx.browser_link(m, ctx.links.folder(folder_token(await lookup.folder_tree(m["id"]), node["id"]))))
        return answer
