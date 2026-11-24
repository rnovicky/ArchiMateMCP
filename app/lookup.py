"""
What the tools are told to look at: a model, an element, a relationship, a
view or a folder, given as the assistant knows it.

An assistant knows things by name more often than by id. Every reference may
therefore be the API's id, an XMI identifier, or a name. A name must point to
one thing: when several match, the lookup fails with the candidates, and the
assistant asks again with an id. It never guesses.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from app.api_client import ApiClient
from app.config import Settings

# How many candidates an ambiguous name lists.
CANDIDATES = 10


class LookupFailed(ToolError):
    """Nothing, or more than one thing, has that name; the message lists the candidates."""


def _is_id(ref: str) -> bool:
    return ref.strip().isdigit()


def _named(items: list[dict], ref: str, key: str = "name") -> list[dict]:
    """The items whose name is `ref` (without regard to case); else those that contain it."""
    wanted = ref.strip().casefold()
    exact = [i for i in items if (i.get(key) or "").casefold() == wanted]
    return exact or [i for i in items if wanted in (i.get(key) or "").casefold()]


def _one(found: list[dict], what: str, ref: str, describe) -> dict:
    if len(found) == 1:
        return found[0]
    if not found:
        raise LookupFailed(f"No {what} is called or identified as \"{ref}\". Use search to find it.")
    listed = "; ".join(describe(i) for i in found[:CANDIDATES])
    more = f" (and {len(found) - CANDIDATES} more)" if len(found) > CANDIDATES else ""
    raise LookupFailed(f"\"{ref}\" matches {len(found)} {what}s: {listed}{more}. Ask again with the id.")


def _element_text(e: dict) -> str:
    return f"{e.get('name') or '(no name)'} ({e['type']}, id {e['id']})"


class Lookup:
    def __init__(self, api: ApiClient, settings: Settings):
        self.api = api
        self.settings = settings

    # ------------------------------------------------------------ models

    async def models(self) -> list[dict]:
        return (await self.api.get("/models", limit=1000))["items"]

    async def model(self, ref: str | int | None) -> dict:
        """A model by id or name; without a reference DEFAULT_MODEL, or the only model there is."""
        ref = str(ref).strip() if ref is not None and str(ref).strip() else self.settings.default_model.strip()
        models = await self.models()
        if not ref:
            if len(models) == 1:
                return models[0]
            if not models:
                raise LookupFailed("The ArchiMate API holds no models.")
            listed = "; ".join(f"{m['name']} (id {m['id']})" for m in models[:CANDIDATES])
            raise LookupFailed(f"Say which model: there are {len(models)}: {listed}.")
        if _is_id(ref):
            for m in models:
                if m["id"] == int(ref):
                    return m
        by_xmi = [m for m in models if m.get("xmiIdentifier") == ref]
        if len(by_xmi) == 1:
            return by_xmi[0]
        return _one(_named(models, ref), "model", ref, lambda m: f"{m['name']} (id {m['id']}, revision {m.get('revision')})")

    # ------------------------------------------------------------ concepts

    async def _xmi(self, model_id: int, ref: str, kind: str) -> int | None:
        found = (await self.api.post(f"/models/{model_id}/resolve", {"xmiIdentifiers": [ref]}))["items"].get(ref)
        return found["id"] if found and found.get("kind") == kind else None

    async def element(self, model_id: int, ref: str | int) -> dict:
        ref = str(ref).strip()
        if _is_id(ref):
            return await self.api.get(f"/models/{model_id}/elements/{ref}")
        element_id = await self._xmi(model_id, ref, "element")
        if element_id is not None:
            return await self.api.get(f"/models/{model_id}/elements/{element_id}")
        # The search ranks a name equal to the text first, so that it is among the first 200
        found = await self.api.get(f"/models/{model_id}/search", q=ref, kinds="elements", **{"in": "name"}, limit=200)
        return _one(_named(found["elements"]["items"], ref), "element", ref, _element_text)

    async def relationship(self, model_id: int, ref: str | int) -> dict:
        """By id or XMI identifier: relationships seldom have names worth looking up."""
        ref = str(ref).strip()
        if not _is_id(ref):
            relationship_id = await self._xmi(model_id, ref, "relationship")
            if relationship_id is None:
                raise LookupFailed(f"No relationship has the id or XMI identifier \"{ref}\". get_element lists "
                                   "an element's relationships with their ids.")
            ref = str(relationship_id)
        return await self.api.get(f"/models/{model_id}/relationships/{ref}")

    async def view(self, model_id: int, ref: str | int) -> dict:
        ref = str(ref).strip()
        if _is_id(ref):
            return await self.api.get(f"/models/{model_id}/views/{ref}")
        view_id = await self._xmi(model_id, ref, "view")
        if view_id is not None:
            return await self.api.get(f"/models/{model_id}/views/{view_id}")
        found = await self.api.get(f"/models/{model_id}/search", q=ref, kinds="views", **{"in": "name"}, limit=200)
        return _one(_named(found["views"]["items"], ref), "view", ref, lambda v: f"{v.get('name')} (id {v['id']})")

    # ------------------------------------------------------------ folders

    async def folder_tree(self, model_id: int) -> list[dict]:
        """The folders of a model, nested, with their counts (API 3.3.0, foldersOnly)."""
        return await self.api.get(f"/models/{model_id}/organizations", counts="true", foldersOnly="true")

    @staticmethod
    def walk(nodes: list[dict], path: tuple[str, ...] = ()):
        """(folder, its path of labels) for every folder of a tree, depth first."""
        for node in nodes:
            here = path + (node.get("label") or "",)
            yield node, here
            yield from Lookup.walk(node.get("children", []), here)

    async def folder(self, model_id: int, ref: str | int) -> tuple[dict, tuple[str, ...]]:
        """A folder by id, by path ("Business/Processes") or by a name only one folder has."""
        tree = await self.folder_tree(model_id)
        ref = str(ref).strip()
        folders = list(self.walk(tree))
        if _is_id(ref):
            for node, path in folders:
                if node["id"] == int(ref):
                    return node, path
            raise LookupFailed(f"Model {model_id} has no folder with the id {ref}.")
        parts = tuple(p.strip().casefold() for p in ref.strip("/").split("/") if p.strip())
        by_path = [(n, p) for n, p in folders if tuple(x.casefold() for x in p) == parts]
        if len(by_path) == 1:
            return by_path[0]
        # A name, or the end of a path: every folder whose path ends so
        ending = [(n, p) for n, p in folders if tuple(x.casefold() for x in p[-len(parts):]) == parts] if parts else []
        if len(ending) == 1:
            return ending[0]
        if not ending:
            raise LookupFailed(f"No folder is at or called \"{ref}\". browse_folders without a folder lists the top level.")
        listed = "; ".join(f"{'/'.join(p)} (id {n['id']})" for n, p in ending[:CANDIDATES])
        raise LookupFailed(f"\"{ref}\" matches {len(ending)} folders: {listed}. Ask again with the path or the id.")


def props(properties: list[dict] | None) -> dict[str, Any]:
    """Property values as {name: value}; a property with several values (languages) as a list."""
    out: dict[str, Any] = {}
    for p in properties or []:
        name = p.get("propertyDefinitionName") or f"property {p.get('propertyDefinitionId')}"
        value = p.get("value")
        if p.get("lang"):
            value = f"{value} ({p['lang']})"
        if name in out:
            out[name] = (out[name] if isinstance(out[name], list) else [out[name]]) + [value]
        else:
            out[name] = value
    return out
