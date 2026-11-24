"""MCP-1 list_models, MCP-2 model_overview.

1.10.0 (API 3.16.0, BL-58): both say where a model is mastered. "file": it is
linked to a file and updated from it, read-only here. "api": it is kept here and
may be changed; `editedSinceImport` counts the changes since its last import,
which a replace from a file would undo.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from app.api_client import ApiError
from app.tools import READ_ONLY, Context, ModelRef, compact, short

# Most property values model_overview lists per property, the most frequent first.
TOP_VALUES = 5


def master(m: dict[str, Any], linked: bool) -> dict[str, Any]:
    """`master` and, for a model kept here, `editedSinceImport` (an API before 3.16.0: from the link alone)."""
    out: dict[str, Any] = {"master": m.get("master") or ("file" if linked else "api")}
    if out["master"] == "api" and m.get("editedSinceImport") is not None:
        out["editedSinceImport"] = m["editedSinceImport"]
    return out


def register(server: MCPServer, ctx: Context) -> None:
    api, lookup = ctx.api, ctx.lookup

    @server.tool(annotations=READ_ONLY)
    @compact
    async def list_models() -> dict[str, Any]:
        """The models the ArchiMate API holds: id, name, size, and where each is mastered.

        Start here when you do not know the model's id or name. `master` "file": the model is linked
        to a file (`linkedTo`), updated from it and read-only here; change it in Archi. "api": it is
        kept here and may be changed; `editedSinceImport` counts the changes since its last import.
        """
        models = await lookup.models()
        links = {link["modelId"]: link for link in (await api.get("/models/links"))["items"]}
        out = []
        for m in models[: ctx.settings.max_results]:
            stats = await api.get(f"/models/{m['id']}/stats")
            entry: dict[str, Any] = {
                "id": m["id"], "name": m["name"], "xmiIdentifier": m.get("xmiIdentifier"),
                "version": m.get("version"), "revision": m.get("revision"),
                "documentation": short(m.get("documentation")),
                "elements": stats["elements"]["total"], "relationships": stats["relationships"]["total"],
                "views": stats["views"]["total"],
                **master(m, m["id"] in links),
            }
            if m["id"] in links:
                link = links[m["id"]]
                entry["linkedTo"] = {"path": link["path"], "intervalMinutes": link.get("intervalMinutes"),
                                     "lastUpdatedAt": link.get("lastUpdatedAt"), "lastStatus": link.get("lastStatus")}
            out.append(entry)
        answer: dict[str, Any] = {"models": out, "total": len(models)}
        if len(models) > len(out):
            answer["truncated"] = True
        if ctx.settings.default_model:
            answer["defaultModel"] = ctx.settings.default_model
        return answer

    @server.tool(annotations=READ_ONLY)
    @compact
    async def model_overview(model: ModelRef = None) -> dict[str, Any]:
        """What a model holds: elements by layer and type, relationships by type, views, top-level folders,
        and the properties in use with their most frequent values.

        Use it to get the lie of the land before searching, and to learn which property names exist.
        `master` says whether the model may be changed here ("api") or is read-only, updated from the
        file it is linked to ("file", with `linkedTo`).
        """
        m = await lookup.model(model)
        stats = await api.get(f"/models/{m['id']}/stats")
        index = await api.get(f"/models/{m['id']}/properties/index", maxValues=TOP_VALUES)
        tree = await lookup.folder_tree(m["id"])
        about: dict[str, Any] = {"id": m["id"], "name": m["name"], "revision": m.get("revision"),
                                 "documentation": m.get("documentation")}
        link = None
        if m.get("master") in ("file", None):
            try:
                link = await api.get(f"/models/{m['id']}/link")
            except ApiError as e:
                if e.status != 404:
                    raise
        about.update(master(m, link is not None))
        if link:
            about["linkedTo"] = {"path": link["path"], "intervalMinutes": link.get("intervalMinutes"),
                                 "lastUpdatedAt": link.get("lastUpdatedAt")}
        return {
            "model": about,
            "elements": {"total": stats["elements"]["total"], "byLayer": stats["elements"]["byLayer"],
                         "byType": stats["elements"]["byType"]},
            "relationships": {"total": stats["relationships"]["total"], "byType": stats["relationships"]["byType"]},
            "views": stats["views"]["total"],
            "folders": [{"id": f["id"], "name": f.get("label"), **f.get("counts", {})} for f in tree],
            "properties": [
                {"name": p["name"], "dataType": p.get("dataType"), "count": p["count"],
                 "distinctValues": p.get("distinctValues"),
                 "topValues": {v["value"]: v["count"] for v in p.get("values", [])}}
                for p in index
            ],
        }
