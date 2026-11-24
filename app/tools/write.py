"""
MCP-15: the write tools, offered only when writing is on (D11).

  create_element, update_element, delete_element
  create_relationship, update_relationship, delete_relationship
  set_property, remove_property
  file_item
  create_folder, update_folder, delete_folder   (1.5.0)
  update_model, update_property_definition, delete_property_definition   (1.6.0)
  update_view, delete_view   (1.9.0, MCP-28): created views; 1.14.0 (API 3.23.0): also views of the model's source on
                             a model mastered here (the API decides); a new view is proposed by propose_view

1.10.0: a refusal because the model is linked to a file (mastered by it, BL-58)
says what the user can do instead.
  apply_changes        many of these in one call and one transaction (1.4.0, API 3.9.0)
  create_model         a new, empty model with Archi's folders (1.4.0; a key that may create models)

One item per call (D18); the API decides what is allowed (its roles, linked
models, RELATIONSHIP_RULES) and its refusals reach the assistant as they are.
A new item gets an XMI identifier like Archi's (D16) and is filed in the
folder of its layer unless the call names one (D17). A likely duplicate is a
warning, never a refusal (D19). Every write is recorded (D20, app/changes.py)
and every answer gives the model's new revision.

1.8.0 (API 3.12.0, T6 of the multi-user epic): a write of an existing item
is checked against the version the assistant saw (`expected_version`, from
get_element, get_relationship, get_view), or else against the version read
in the same call; the API refuses it (412) when someone changed the item
since, and the assistant is told who changed what. D15 ("the last write
wins") no longer holds.

1.12.0 (API with REQUIRE_IF_MATCH=true, which refuses a change that says no
version): every write of an existing item sends one, also file_item,
delete_folder (both now one operation of the changes endpoint), the model's
own properties and every change of apply_changes (unless expected_revision
covers the model). A version read in the same call guards only against a
change made between that read and the write, not against one made since the
assistant showed the item to the user: only expected_version does that.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from app import changes
from app.api_client import ApiError
from app.tools import Context, ModelRef, Ref, compact, element_summary, page

# Writes add or change; deletes remove (clients ask the user before those, D14).
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
UPDATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
DELETE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)

# D17: the top-level folders Archi makes, by layer of the API's metamodel; the first that exists is used.
LAYER_FOLDERS: dict[str, tuple[str, ...]] = {
    "Strategy": ("Strategy",),
    "Business": ("Business",),
    "Application": ("Application",),
    "Technology": ("Technology & Physical", "Technology"),
    "Physical": ("Technology & Physical", "Physical"),
    "Motivation": ("Motivation",),
    "ImplementationMigration": ("Implementation & Migration",),
    "Other": ("Other",),
}
RELATIONS_FOLDERS = ("Relations",)
# The top-level folders Archi gives a new model, in its order.
ARCHI_FOLDERS = ("Strategy", "Business", "Application", "Technology & Physical", "Motivation",
                 "Implementation & Migration", "Other", "Relations", "Views")

Kind = Literal["element", "relationship", "view"]
ItemKind = Annotated[Kind, Field(description="What `item` is: element (default), relationship or view.")]
OwnerKind = Annotated[Literal["element", "relationship", "view", "model"], Field(
    description="What `item` is: element (default), relationship or view; model: the model itself (no `item`).")]
DataType = Literal["string", "boolean", "currency", "date", "time", "number"]
FolderRef = Annotated[Ref | None, Field(
    description="The folder to file it in: id, path (\"Business/Processes\") or a name only one folder has. "
                "Default: the top-level folder of its layer (relationships: \"Relations\").")]
XmiRef = Annotated[str | None, Field(description="Its XMI identifier; default: a new one like Archi's.")]
Properties = Annotated[dict[str, str] | None, Field(description="Property values to set: {name: value}.")]
ExpectedVersion = Annotated[str | None, Field(description=(
    "The item's `version` as get_element, get_relationship or get_view gave it when you showed it to the user. "
    "The change is refused if someone changed the item since. Without it, the version read in this call is used."))]

ChangeOp = Literal["createElement", "updateElement", "deleteElement", "createRelationship", "updateRelationship",
                   "deleteRelationship", "setProperty", "removeProperty", "fileItem", "createFolder", "updateFolder",
                   "deleteFolder", "updateView", "deleteView"]


class Change(BaseModel):
    """One change of apply_changes. Which fields an operation takes is in the tool's description."""

    op: ChangeOp
    ref: str | None = Field(None, description="A name for the item this operation creates; later ones refer to it as \"@name\"")
    element: Ref | None = Field(None, description="The element: id, XMI identifier, name, or \"@ref\"")
    relationship: Ref | None = Field(None, description="The relationship: id, XMI identifier, or \"@ref\"")
    item: Ref | None = Field(None, description="setProperty, removeProperty, fileItem: the element, relationship or view (`kind`)")
    kind: Kind = "element"
    type: str | None = None
    name: str | None = Field(None, description="A name; in an update, \"\" removes it")
    documentation: str | None = Field(None, description="Documentation; in an update, \"\" removes it")
    source: Ref | None = Field(None, description="The source element: id, XMI identifier, name, or \"@ref\"")
    target: Ref | None = Field(None, description="The target element: id, XMI identifier, name, or \"@ref\"")
    source_relationship: Ref | None = Field(None, description="Instead of `source`: a relationship (id or \"@ref\")")
    target_relationship: Ref | None = Field(None, description="Instead of `target`: a relationship (id or \"@ref\")")
    access_type: Literal["Access", "Read", "Write", "ReadWrite"] | None = None
    influence_modifier: str | None = None
    is_directed: bool | None = None
    folder: Ref | None = Field(None, description="createElement, createRelationship (default: the folder of its layer), "
                                                "fileItem; updateFolder, deleteFolder: the folder they change. A folder "
                                                "made by an earlier change as \"@ref\"")
    parent: Ref | None = Field(None, description="createFolder, updateFolder: the folder to make or move it in; \"/\" "
                                                "the top level")
    move_contents_to: Ref | None = Field(None, description="deleteFolder: where its sub-folders and items go first")
    view: Ref | None = Field(None, description="updateView, deleteView: the created view: id, XMI identifier or name")
    properties: dict[str, str] | None = None
    value: str | None = None
    lang: str | None = None
    cascade: bool = False
    xmi_identifier: str | None = None
    expected_version: str | None = Field(None, description="updateElement, deleteElement, updateRelationship, "
                                         "deleteRelationship, updateFolder, deleteFolder, updateView, deleteView: "
                                         "the item's `version`; "
                                         "setProperty, removeProperty, fileItem: its owner's. Refused if it changed")



def new_identifier() -> str:
    """D16: an XMI identifier like the ones Archi makes."""
    return f"id-{uuid.uuid4().hex}"


def _relationship_text(r: dict) -> dict[str, Any]:
    return {"id": r["id"], "type": r["type"], "name": r.get("name"),
            "source": r.get("sourceElementId") or r.get("sourceRelationshipId"),
            "target": r.get("targetElementId") or r.get("targetRelationshipId")}


def register(server: MCPServer, ctx: Context) -> None:
    api, lookup = ctx.api, ctx.lookup
    layers: dict[str, str] = {}  # element type -> layer, from GET /metamodel, read once

    # ------------------------------------------------------------ helpers

    async def layer_of(element_type: str) -> str | None:
        if not layers:
            for layer in (await api.get("/metamodel"))["layers"]:
                for t in layer["elementTypes"]:
                    layers[t] = layer["key"]
        return layers.get(element_type)

    async def target_folder(model_id: int, folder: Ref | None, labels: tuple[str, ...]) -> tuple[dict | None, tuple[str, ...]]:
        """The folder named, or the first top-level folder with one of `labels`; (None, ()) without one."""
        if folder is not None and str(folder).strip():
            return await lookup.folder(model_id, folder)
        tops = {(node.get("label") or "").casefold(): node for node in await lookup.folder_tree(model_id)}
        for label in labels:
            if label.casefold() in tops:
                node = tops[label.casefold()]
                return node, (node.get("label") or "",)
        return None, ()

    async def file_new(model_id: int, kind: str, item_id: int, folder: Ref | None, labels: tuple[str, ...],
                       warnings: list[str]) -> str | None:
        node, path = await target_folder(model_id, folder, labels)
        if node is None:
            warnings.append(f"Filed in no folder: the model has no top-level folder {' or '.join(map(repr, labels))}. "
                            "file_item files it.")
            return None
        await add_leaf(model_id, node["id"], kind, item_id)
        return "/".join(path)

    async def add_leaf(model_id: int, folder_id: int, kind: str, item_id: int) -> None:
        children = (await api.get(f"/models/{model_id}/organizations/{folder_id}")).get("children", [])
        order = max((c.get("sortOrder", 0) for c in children), default=-1) + 1
        await api.post(f"/models/{model_id}/organizations",
                       {"parentId": folder_id, f"ref{kind.capitalize()}Id": item_id, "sortOrder": order})

    async def revision(model_id: int) -> int | None:
        return (await api.get(f"/models/{model_id}")).get("revision")

    async def item_of(model_id: int, kind: str, ref: Ref) -> dict:
        return await {"element": lookup.element, "relationship": lookup.relationship, "view": lookup.view}[kind](model_id, ref)

    async def definition(model_id: int, name: str, create: bool) -> dict | None:
        """The property definition with this name; made (as a string property) when `create`."""
        defs = await api.get(f"/models/{model_id}/property-definitions")
        defs = defs.get("items", defs) if isinstance(defs, dict) else defs
        for d in defs:
            if (d.get("name") or "") == name:
                return d
        if not create:
            return None
        return await api.post(f"/models/{model_id}/property-definitions",
                              {"xmiIdentifier": f"propid-{uuid.uuid4().hex}", "name": name, "dataType": "string"})

    def properties_path(model_id: int, kind: str, item: dict) -> str:
        return f"/models/{model_id}/properties" if kind == "model" else f"/models/{model_id}/{kind}s/{item['id']}/properties"

    async def owner_of(model: dict, kind: str, ref: Ref | None) -> dict:
        """The element, relationship or view; for kind model the model itself, with its properties."""
        if kind == "model":
            found = await api.get(f"/models/{model['id']}/properties", limit=1000)
            return {"id": model["id"], "name": model.get("name"), "properties": found.get("items", [])}
        if ref is None or not str(ref).strip():
            raise ToolError(f"It needs `item`: the {kind}.")
        return await item_of(model["id"], kind, ref)

    async def put_property(model_id: int, kind: str, item: dict, name: str, value: str, lang: str | None) -> str | None:
        """Set one property value; returns the value it replaced, or None."""
        base = properties_path(model_id, kind, item)
        for p in item.get("properties") or []:
            if p.get("propertyDefinitionName") == name and (p.get("lang") or None) == (lang or None):
                await api.put(f"{base}/{p['id']}", {"value": value, **({"lang": lang} if lang else {})},
                              if_match=p.get("version"))
                return p.get("value")
        d = await definition(model_id, name, create=True)
        await api.post(base, {"propertyDefinitionId": d["id"], "value": value, **({"lang": lang} if lang else {})})
        return None

    def record(tool: str, model: dict, item: dict[str, Any], change: dict[str, Any]) -> None:
        changes.record(ctx.settings, ctx.key_name, tool, model, item, change)

    def refused(e: ApiError) -> ToolError:
        """A refusal of the API, with a hint where the assistant can do something about it."""
        body = e.body if isinstance(e.body, dict) else {}
        if body.get("code") == "RELATIONSHIP_NOT_ALLOWED":
            return ToolError(f"{e} Choose an allowed type (allowed_relationships lists them), or other ends.")
        if e.status == 409 and "comes from the model's source" in str(e):
            # an API before 3.23.0, or a change of what a source view shows
            return ToolError(f"{e} What a view of the model's source shows is never changed here. To have it "
                             "otherwise, propose a new view with propose_view; the user saves it in the ArchiMate Browser.")
        if e.status == 409 and " is linked to " in str(e):
            # 1.10.0 (BL-58): a file-mastered model; say what the user can do instead
            return ToolError(f"{e} Nothing was changed. The model is mastered by its file (model_overview: master "
                             "\"file\"): tell the user to make the change in Archi and save the file, which "
                             "updates the model here; or, to edit it here from now on, to unlink the model (an "
                             "admin, in the ArchiMate Browser). A new view can still be proposed with propose_view.")
        if body.get("code") == "PRECONDITION_FAILED":
            return ToolError(f"{e} Nothing was changed. Read it again, tell the user what changed and by whom, and "
                             "ask whether to make the change anyway; then call again with the new version.")
        return e

    async def changes_call(model_id: int, operation: dict[str, Any]) -> dict[str, Any]:
        """One operation of the changes endpoint (a property, checked against its owner's version); its result."""
        try:
            done = await api.post(f"/models/{model_id}/changes", {"operations": [
                {k: v for k, v in operation.items() if v is not None}]})
        except ApiError as e:
            raise refused(e) from e
        return done["results"][0]

    # ------------------------------------------------------------ elements

    @server.tool(annotations=WRITE)
    @compact
    async def create_element(
        type: Annotated[str, Field(description="The element type as the API names it, e.g. ApplicationComponent, "
                                               "BusinessProcess (archimate://metamodel lists them).")],
        name: Annotated[str, Field(description="Its name.")],
        model: ModelRef = None,
        documentation: Annotated[str | None, Field(description="Its documentation.")] = None,
        folder: FolderRef = None,
        properties: Properties = None,
        xmi_identifier: XmiRef = None,
    ) -> dict[str, Any]:
        """Create an element, file it in a folder and set its properties.

        Search first: an element of the same type and name is reported as a likely duplicate (it is still created).
        """
        m = await lookup.model(model)
        warnings: list[str] = []
        same = await api.get(f"/models/{m['id']}/elements", type=type, name=name.strip(), limit=20)
        twins = [e for e in same.get("items", []) if (e.get("name") or "").strip().casefold() == name.strip().casefold()]
        if twins:
            warnings.append("Likely a duplicate of " + ", ".join(f"{e.get('name')} (id {e['id']})" for e in twins) + ".")
        try:
            created = await api.post(f"/models/{m['id']}/elements", {
                "xmiIdentifier": xmi_identifier or new_identifier(), "type": type, "name": name,
                **({"documentation": documentation} if documentation else {})})
        except ApiError as e:
            raise refused(e) from e
        layer = await layer_of(created["type"])
        filed = await file_new(m["id"], "element", created["id"], folder, LAYER_FOLDERS.get(layer or "", ()), warnings)
        for key, value in (properties or {}).items():
            await put_property(m["id"], "element", created, key, str(value), None)
        record("create_element", m, element_summary(created), {"name": name, "type": type, "folder": filed,
                                                                "properties": properties or None})
        answer: dict[str, Any] = {"created": {**element_summary(created), "xmiIdentifier": created["xmiIdentifier"]},
                                  "folder": filed, "revision": await revision(m["id"])}
        if properties:
            answer["properties"] = properties
        if warnings:
            answer["warnings"] = warnings
        return answer

    @server.tool(annotations=UPDATE)
    @compact
    async def update_element(
        element: Annotated[Ref, Field(description="The element: id, XMI identifier or name.")],
        model: ModelRef = None,
        name: Annotated[str | None, Field(description="A new name.")] = None,
        documentation: Annotated[str | None, Field(description="New documentation; \"\" removes it.")] = None,
        type: Annotated[str | None, Field(description="A new element type. Its relationships must still be "
                                                      "allowed (the API checks).")] = None,
        expected_version: ExpectedVersion = None,
    ) -> dict[str, Any]:
        """Change an element's name, documentation or type. Give only what changes."""
        m = await lookup.model(model)
        e = await lookup.element(m["id"], element)
        body = {k: v for k, v in (("name", name), ("type", type)) if v is not None}
        if documentation is not None:
            body["documentation"] = documentation or None
        if not body:
            raise ToolError("Nothing to change: give name, documentation or type.")
        try:
            updated = await api.put(f"/models/{m['id']}/elements/{e['id']}", body,
                                    if_match=expected_version or e.get("version"))
        except ApiError as err:
            raise refused(err) from err
        before = {k: e.get(k) for k in body}
        record("update_element", m, element_summary(e), {"before": before, "after": body})
        answer: dict[str, Any] = {"updated": element_summary(updated), "before": before,
                                  "revision": await revision(m["id"])}
        if updated.get("warnings"):
            answer["warnings"] = updated["warnings"]
        return answer

    @server.tool(annotations=DELETE)
    @compact
    async def delete_element(
        element: Annotated[Ref, Field(description="The element: id, XMI identifier or name.")],
        model: ModelRef = None,
        cascade: Annotated[bool, Field(description="Also when it has relationships or is shown in views: those "
                                                   "relationships are deleted and it disappears from the views.")] = False,
        expected_version: ExpectedVersion = None,
    ) -> dict[str, Any]:
        """Delete an element. One that has relationships or is shown in views is refused first, with what would go
        with it: tell the user and ask, and call again with cascade=true only when they agree. The answer lists what
        went with it."""
        m = await lookup.model(model)
        e = await lookup.element(m["id"], element)
        base = f"/models/{m['id']}"
        rels = []
        for end in ("sourceElementId", "targetElementId"):
            rels += (await api.get(f"{base}/relationships", **{end: e["id"]}, limit=1000))["items"]
        rels = list({r["id"]: r for r in rels}.values())
        views = (await api.get(f"{base}/elements/{e['id']}/views", limit=1000))["items"]
        shown = [{"id": u["view"]["id"], "name": u["view"].get("name")} for u in views]
        if (rels or shown) and not cascade:
            raise ToolError(
                f"{e.get('name') or e['id']} has {len(rels)} relationship(s) and is shown in {len(shown)} view(s)"
                + (f" ({', '.join(v['name'] or str(v['id']) for v in shown[:5])})" if shown else "")
                + ". Tell the user what would go with it and ask; only when they agree, call again with cascade=true "
                "to delete it with its relationships and take it out of those views.")
        try:
            await api.delete(f"{base}/elements/{e['id']}", if_match=expected_version or e.get("version"))
        except ApiError as err:
            raise refused(err) from err
        n = ctx.limit(None)
        record("delete_element", m, element_summary(e), {"relationships": [r["id"] for r in rels],
                                                          "views": [v["id"] for v in shown]})
        return {"deleted": element_summary(e),
                "alsoDeleted": {"relationships": page([_relationship_text(r) for r in rels[:n]], len(rels)),
                                "removedFromViews": page(shown[:n], len(shown))},
                "revision": await revision(m["id"])}

    # ------------------------------------------------------------ relationships

    async def end(model_id: int, element: Ref | None, relationship: int | None, side: str) -> dict:
        if (element is None) == (relationship is None):
            raise ToolError(f"Give exactly one {side}: an element ({side}) or a relationship ({side}_relationship).")
        if element is not None:
            e = await lookup.element(model_id, element)
            return {f"{side}ElementId": e["id"], f"{side}RelationshipId": None, "_text": e.get("name") or e["id"]}
        r = await lookup.relationship(model_id, relationship)
        return {f"{side}RelationshipId": r["id"], f"{side}ElementId": None, "_text": f"relationship {r['id']}"}

    @server.tool(annotations=WRITE)
    @compact
    async def create_relationship(
        type: Annotated[str, Field(description="The relationship type, e.g. Serving, Realization, Flow.")],
        source: Annotated[Ref | None, Field(description="The source element: id, XMI identifier or name.")] = None,
        target: Annotated[Ref | None, Field(description="The target element: id, XMI identifier or name.")] = None,
        model: ModelRef = None,
        name: Annotated[str | None, Field(description="Its name.")] = None,
        documentation: Annotated[str | None, Field(description="Its documentation.")] = None,
        source_relationship: Annotated[int | None, Field(description="Instead of `source`: a relationship (id) "
                                                                     "as the source.")] = None,
        target_relationship: Annotated[int | None, Field(description="Instead of `target`: a relationship (id) "
                                                                     "as the target, e.g. for an Association.")] = None,
        access_type: Annotated[Literal["Access", "Read", "Write", "ReadWrite"] | None,
                               Field(description="For Access: how the data is accessed.")] = None,
        influence_modifier: Annotated[str | None, Field(description="For Influence: e.g. +, ++, -, --.")] = None,
        is_directed: Annotated[bool | None, Field(description="For Association: whether it has a direction.")] = None,
        folder: FolderRef = None,
        properties: Properties = None,
        xmi_identifier: XmiRef = None,
    ) -> dict[str, Any]:
        """Create a relationship between two elements (or with a relationship as an end), file it and set its
        properties. ArchiMate's rules apply: the API refuses a type it does not allow between the two."""
        m = await lookup.model(model)
        src = await end(m["id"], source, source_relationship, "source")
        tgt = await end(m["id"], target, target_relationship, "target")
        warnings: list[str] = []
        ends = {k: v for k, v in {**src, **tgt}.items() if not k.startswith("_")}
        query = {k: v for k, v in ends.items() if v is not None}
        same = [r for r in (await api.get(f"/models/{m['id']}/relationships", type=type, limit=50, **query))["items"]
                if all(r.get(k) == v for k, v in ends.items())]
        if same:
            warnings.append("Likely a duplicate of relationship " + ", ".join(str(r["id"]) for r in same) + ".")
        body = {"xmiIdentifier": xmi_identifier or new_identifier(), "type": type, **ends,
                **{k: v for k, v in (("name", name), ("documentation", documentation), ("accessType", access_type),
                                     ("influenceModifier", influence_modifier), ("isDirected", is_directed)) if v is not None}}
        try:
            created = await api.post(f"/models/{m['id']}/relationships", body)
        except ApiError as e:
            raise refused(e) from e
        warnings += created.get("warnings", [])
        filed = await file_new(m["id"], "relationship", created["id"], folder, RELATIONS_FOLDERS, warnings)
        for key, value in (properties or {}).items():
            await put_property(m["id"], "relationship", created, key, str(value), None)
        summary = _relationship_text(created)
        record("create_relationship", m, summary, {"type": type, "source": src["_text"], "target": tgt["_text"],
                                                    "folder": filed, "properties": properties or None})
        answer: dict[str, Any] = {"created": {**summary, "xmiIdentifier": created["xmiIdentifier"]},
                                  "between": f"{src['_text']} -> {tgt['_text']}", "folder": filed,
                                  "revision": await revision(m["id"])}
        if properties:
            answer["properties"] = properties
        if warnings:
            answer["warnings"] = warnings
        return answer

    @server.tool(annotations=UPDATE)
    @compact
    async def update_relationship(
        relationship: Annotated[Ref, Field(description="The relationship: id or XMI identifier.")],
        model: ModelRef = None,
        type: Annotated[str | None, Field(description="A new type.")] = None,
        name: Annotated[str | None, Field(description="A new name; \"\" removes it.")] = None,
        documentation: Annotated[str | None, Field(description="New documentation; \"\" removes it.")] = None,
        source: Annotated[Ref | None, Field(description="A new source element.")] = None,
        target: Annotated[Ref | None, Field(description="A new target element.")] = None,
        access_type: Annotated[Literal["Access", "Read", "Write", "ReadWrite"] | None, Field(description="For Access.")] = None,
        influence_modifier: Annotated[str | None, Field(description="For Influence.")] = None,
        is_directed: Annotated[bool | None, Field(description="For Association.")] = None,
        expected_version: ExpectedVersion = None,
    ) -> dict[str, Any]:
        """Change a relationship: its type, name, documentation, ends or attributes. Give only what changes.
        The result must still be allowed by ArchiMate's rules (the API checks)."""
        m = await lookup.model(model)
        r = await lookup.relationship(m["id"], relationship)
        body: dict[str, Any] = {k: v for k, v in (("type", type), ("accessType", access_type),
                                                  ("influenceModifier", influence_modifier), ("isDirected", is_directed))
                                if v is not None}
        for key, value in (("name", name), ("documentation", documentation)):
            if value is not None:
                body[key] = value or None
        if source is not None:
            body["sourceElementId"] = (await lookup.element(m["id"], source))["id"]
        if target is not None:
            body["targetElementId"] = (await lookup.element(m["id"], target))["id"]
        if not body:
            raise ToolError("Nothing to change.")
        try:
            updated = await api.put(f"/models/{m['id']}/relationships/{r['id']}", body,
                                    if_match=expected_version or r.get("version"))
        except ApiError as e:
            raise refused(e) from e
        before = {k: r.get(k) for k in body}
        record("update_relationship", m, _relationship_text(r), {"before": before, "after": body})
        answer: dict[str, Any] = {"updated": _relationship_text(updated), "before": before,
                                  "revision": await revision(m["id"])}
        if updated.get("warnings"):
            answer["warnings"] = updated["warnings"]
        return answer

    @server.tool(annotations=DELETE)
    @compact
    async def delete_relationship(
        relationship: Annotated[Ref, Field(description="The relationship: id or XMI identifier.")],
        model: ModelRef = None,
        expected_version: ExpectedVersion = None,
    ) -> dict[str, Any]:
        """Delete a relationship. Relationships attached to it (an Association on it, for example) go with it, and it
        disappears from the views that show it; the answer lists both. Ask the user before deleting."""
        m = await lookup.model(model)
        r = await lookup.relationship(m["id"], relationship)
        base = f"/models/{m['id']}"
        attached = []
        for end_key in ("sourceRelationshipId", "targetRelationshipId"):
            attached += (await api.get(f"{base}/relationships", **{end_key: r["id"]}, limit=1000))["items"]
        views = (await api.get(f"{base}/relationships/{r['id']}/views", limit=1000))["items"]
        shown = [{"id": u["view"]["id"], "name": u["view"].get("name")} for u in views]
        try:
            await api.delete(f"{base}/relationships/{r['id']}", if_match=expected_version or r.get("version"))
        except ApiError as e:
            raise refused(e) from e
        record("delete_relationship", m, _relationship_text(r), {"attached": [a["id"] for a in attached],
                                                                  "views": [v["id"] for v in shown]})
        n = ctx.limit(None)
        return {"deleted": _relationship_text(r),
                "alsoDeleted": {"attachedRelationships": page([_relationship_text(a) for a in attached[:n]], len(attached)),
                                "removedFromViews": page(shown[:n], len(shown))},
                "revision": await revision(m["id"])}

    # ------------------------------------------------------------ properties

    @server.tool(annotations=UPDATE)
    @compact
    async def set_property(
        name: Annotated[str, Field(description="The property's name; a new name makes a new property definition.")],
        value: Annotated[str, Field(description="Its value.")],
        item: Annotated[Ref | None, Field(description="The element, relationship or view (see `kind`); none for the "
                                                      "model's own properties.")] = None,
        model: ModelRef = None,
        kind: OwnerKind = "element",
        lang: Annotated[str | None, Field(description="The language of the value (e.g. en, cs), for properties with "
                                                      "a value per language.")] = None,
        expected_version: Annotated[str | None, Field(description=(
            "The `version` of the element, relationship or view (not for kind=model) as you showed it to the user; "
            "refused if someone changed it since. Without it, the version read in this call is used."))] = None,
    ) -> dict[str, Any]:
        """Set a property of an element, relationship, view or of the model itself: a new value, or a new one in
        place of the old."""
        m = await lookup.model(model)
        it = await owner_of(m, kind, item)
        if kind == "model":
            if expected_version:
                raise ToolError("expected_version is for an element, relationship or view, not for kind=model.")
            previous = await put_property(m["id"], kind, it, name, value, lang)
        else:
            previous = (await changes_call(m["id"], {
                "op": "setProperty", "owner": {"kind": kind, "id": it["id"]}, "name": name, "value": value, "lang": lang,
                "expectedVersion": expected_version or it.get("version")})).get("previous")
        summary = {"kind": kind, "id": it["id"], "name": it.get("name")}
        record("set_property", m, summary, {"property": name, "lang": lang, "before": previous, "after": value})
        return {"item": summary, "property": name, "value": value, "previous": previous,
                "revision": await revision(m["id"])}

    @server.tool(annotations=DELETE)
    @compact
    async def remove_property(
        name: Annotated[str, Field(description="The property's name.")],
        item: Annotated[Ref | None, Field(description="The element, relationship or view (see `kind`); none for the "
                                                      "model's own properties.")] = None,
        model: ModelRef = None,
        kind: OwnerKind = "element",
        lang: Annotated[str | None, Field(description="Only the value in this language; default: every value.")] = None,
        expected_version: Annotated[str | None, Field(description=(
            "The `version` of the element, relationship or view (not for kind=model) as you showed it to the user; "
            "refused if someone changed it since. Without it, the version read in this call is used."))] = None,
    ) -> dict[str, Any]:
        """Remove a property's value(s) from an element, relationship, view or the model itself."""
        m = await lookup.model(model)
        it = await owner_of(m, kind, item)
        found = [p for p in it.get("properties") or [] if p.get("propertyDefinitionName") == name
                 and (lang is None or (p.get("lang") or None) == lang)]
        if not found:
            raise ToolError(f"{it.get('name') or it['id']} has no property \"{name}\"" + (f" in {lang}" if lang else "") + ".")
        if kind == "model":
            if expected_version:
                raise ToolError("expected_version is for an element, relationship or view, not for kind=model.")
            for p in found:
                await api.delete(f"{properties_path(m['id'], kind, it)}/{p['id']}", if_match=p.get("version"))
        else:
            await changes_call(m["id"], {"op": "removeProperty", "owner": {"kind": kind, "id": it["id"]}, "name": name,
                                         "lang": lang, "expectedVersion": expected_version or it.get("version")})
        summary = {"kind": kind, "id": it["id"], "name": it.get("name")}
        removed = [{"value": p.get("value"), **({"lang": p["lang"]} if p.get("lang") else {})} for p in found]
        record("remove_property", m, summary, {"property": name, "removed": removed})
        return {"item": summary, "property": name, "removed": removed, "revision": await revision(m["id"])}

    # ------------------------------------------------------------ many changes at once (1.4.0)

    @server.tool(annotations=DELETE)
    @compact
    async def apply_changes(
        changes: Annotated[list[Change], Field(min_length=1, max_length=1000, description=(
            "The changes, applied in order. Fields per op: createElement: type, name, documentation, folder, "
            "properties, ref. updateElement: element, and name, documentation or type. deleteElement: element, "
            "cascade. createRelationship: type, source or source_relationship, target or target_relationship, name, "
            "documentation, access_type, influence_modifier, is_directed, folder, properties, ref. "
            "updateRelationship: relationship, and what changes (type, name, documentation, source, target, "
            "access_type, influence_modifier, is_directed). deleteRelationship: relationship. setProperty: item, "
            "kind, name, value, lang. removeProperty: item, kind, name, lang. fileItem: item, kind, folder. "
            "createFolder: name, parent (default: the top level), documentation, ref. updateFolder: folder, and name, "
            "documentation or parent (\"/\": the top level). deleteFolder: folder, move_contents_to (only if the "
            "user said where). updateView: view, and name or documentation (created views only). deleteView: view "
            "(a created view; ask the user first). Any change of an existing item may carry expected_version: the version you showed "
            "the user (for setProperty, removeProperty, fileItem: of the item that owns it); if someone changed it "
            "since, nothing is applied."))],
        model: ModelRef = None,
        expected_revision: Annotated[int | None, Field(description="Apply only if the model is still at this revision "
                                                                   "(from an earlier answer): nobody changed it since.")] = None,
    ) -> dict[str, Any]:
        """Many changes to a model in one call and one transaction: all of them, or none.

        Use it for more than two or three changes: a clean-up (renaming, retyping, re-filing), or a piece of a model
        built at once (elements and the relationships between them). An item created by one change is named by later
        ones as "@" and the `ref` it was given, e.g. {"op": "createElement", "ref": "crm", ...} then
        {"op": "createRelationship", "source": "@crm", ...}. Existing items by id, XMI identifier or name, folders
        by id or path. A folder made by one change takes later items as "folder": "@its ref". The first change that
        fails undoes all of them, and the error names it. ArchiMate's relationship rules apply.
        """
        m = await lookup.model(model)
        operations, labels = [], []
        # 1.12.0: without expected_revision, a change of an existing item that gives no expected_version is
        # checked against the item's version as read now (once per item), as the single tools do
        versions: dict[tuple[str, int], str | None] | None = {} if expected_revision is None else None
        for index, change in enumerate(changes, start=1):
            try:
                operations.append(await to_operation(m["id"], change, versions))
            except ToolError as e:
                raise ToolError(f"Change {index} ({change.op}): {e}") from e
            labels.append(change)
        body: dict[str, Any] = {"operations": operations}
        if expected_revision is not None:
            body["expectedRevision"] = expected_revision
        try:
            done = await api.post(f"/models/{m['id']}/changes", body)
        except ApiError as e:
            raise refused(e) from e
        n = ctx.limit(None)
        results = []
        for result, change in zip(done["results"], labels):
            entry = {"op": result["op"], "kind": result.get("kind"), "id": result.get("id")}
            for key in ("name", "label", "type", "xmiIdentifier", "before", "previous", "removed", "relationships",
                        "attached", "moved"):
                if result.get(key) not in (None, [], {}):
                    entry[key] = result[key]
            if change.ref:
                entry["ref"] = change.ref
            results.append(entry)
            record("apply_changes", m, {"kind": result.get("kind"), "id": result.get("id")},
                   {"op": result["op"], **{k: v for k, v in change.model_dump(exclude_none=True).items()
                                           if k not in ("op", "kind", "cascade") or v}})
        counts: dict[str, int] = {}
        for r in done["results"]:
            counts[r["op"]] = counts.get(r["op"], 0) + 1
        answer: dict[str, Any] = {"applied": len(done["results"]), "byOperation": counts,
                                  "results": page(results[:n], len(results)), "revision": done["revision"]}
        if done.get("warnings"):
            answer["warnings"] = done["warnings"]
        return answer

    async def to_operation(model_id: int, c: Change,
                           versions: dict[tuple[str, int], str | None] | None = None) -> dict[str, Any]:
        """A change in the API's terms: references resolved to ids or refs, folders to ids (D17 for new items).
        With `versions` (a cache of one call), a change of an existing item without expected_version gets the
        version the item has now."""
        async def item(kind: str, ref: Ref | None, what: str) -> dict[str, Any]:
            if ref is None or not str(ref).strip():
                raise ToolError(f"It needs `{what}`.")
            text = str(ref).strip()
            if text.startswith("@"):
                return {"ref": text[1:]}
            if text.isdigit():
                return {"id": int(text)}
            return {"id": (await item_of(model_id, kind, text))["id"]}

        async def end(element: Ref | None, relationship: Ref | None, side: str) -> dict[str, Any] | None:
            if element is None and relationship is None:
                return None
            if element is not None and relationship is not None:
                raise ToolError(f"Give `{side}` or `{side}_relationship`, not both.")
            if element is not None:
                found = await item("element", element, side)
                return {"elementRef": found["ref"]} if "ref" in found else {"elementId": found["id"]}
            found = await item("relationship", relationship, f"{side}_relationship")
            return {"relationshipRef": found["ref"]} if "ref" in found else {"relationshipId": found["id"]}

        async def folder_field(ref: Ref | None, labels: tuple[str, ...] | None) -> dict[str, Any]:
            """{"folderId": …} or {"folderRef": …}; for a new item without one, the folder of its layer (D17)."""
            if ref is not None and str(ref).strip():
                text = str(ref).strip()
                if text.startswith("@"):
                    return {"folderRef": text[1:]}
                return {"folderId": (await lookup.folder(model_id, text))[0]["id"]}
            if labels:
                node, _ = await target_folder(model_id, None, labels)
                return {"folderId": node["id"]} if node else {}
            return {}

        async def folder_item(ref: Ref | None, what: str) -> dict[str, Any]:
            if ref is None or not str(ref).strip():
                raise ToolError(f"It needs `{what}`.")
            text = str(ref).strip()
            if text.startswith("@"):
                return {"ref": text[1:]}
            return {"id": (await lookup.folder(model_id, text))[0]["id"]}

        def cleared(value: str | None) -> str | None:
            return value or None

        op: dict[str, Any] = {"op": c.op}
        explicit: set[str] = set()  # fields an update sets to null: they are sent
        if c.op == "createElement":
            if not c.type:
                raise ToolError("It needs `type`.")
            layer = await layer_of(c.type)
            op.update(type=c.type, name=c.name, documentation=c.documentation, ref=c.ref, xmiIdentifier=c.xmi_identifier,
                      **await folder_field(c.folder, LAYER_FOLDERS.get(layer or "", ())), properties=c.properties or {})
        elif c.op == "updateElement":
            op["element"] = await item("element", c.element, "element")
            fields = {k: v for k, v in (("type", c.type), ("xmiIdentifier", c.xmi_identifier)) if v is not None}
            fields.update({k: cleared(v) for k, v in (("name", c.name), ("documentation", c.documentation)) if v is not None})
            if not fields:
                raise ToolError("Nothing to change: give name, documentation or type.")
            op.update(fields)
            explicit |= fields.keys()
        elif c.op == "deleteElement":
            op.update(element=await item("element", c.element, "element"), cascade=c.cascade)
        elif c.op == "createRelationship":
            if not c.type:
                raise ToolError("It needs `type`.")
            source = await end(c.source, c.source_relationship, "source")
            target = await end(c.target, c.target_relationship, "target")
            if source is None or target is None:
                raise ToolError("It needs a source and a target.")
            op.update(type=c.type, source=source, target=target, name=c.name, documentation=c.documentation, ref=c.ref,
                      xmiIdentifier=c.xmi_identifier, accessType=c.access_type, influenceModifier=c.influence_modifier,
                      isDirected=c.is_directed, **await folder_field(c.folder, RELATIONS_FOLDERS),
                      properties=c.properties or {})
        elif c.op == "updateRelationship":
            op["relationship"] = await item("relationship", c.relationship, "relationship")
            fields = {k: v for k, v in (("type", c.type), ("xmiIdentifier", c.xmi_identifier), ("accessType", c.access_type),
                                        ("influenceModifier", c.influence_modifier), ("isDirected", c.is_directed)) if v is not None}
            fields.update({k: cleared(v) for k, v in (("name", c.name), ("documentation", c.documentation)) if v is not None})
            for side, element, relationship in (("source", c.source, c.source_relationship), ("target", c.target, c.target_relationship)):
                found = await end(element, relationship, side)
                if found:
                    fields[side] = found
            if not fields:
                raise ToolError("Nothing to change.")
            op.update(fields)
            explicit |= fields.keys()
        elif c.op == "deleteRelationship":
            op["relationship"] = await item("relationship", c.relationship, "relationship")
        elif c.op in ("setProperty", "removeProperty"):
            if not c.name:
                raise ToolError("It needs the property's `name`.")
            op.update(owner={"kind": c.kind, **await item(c.kind, c.item, "item")}, name=c.name, lang=c.lang)
            if c.op == "setProperty":
                if c.value is None:
                    raise ToolError("It needs a `value`.")
                op["value"] = c.value
        elif c.op == "fileItem":
            if c.folder is None:
                raise ToolError("It needs a `folder`.")
            op.update(item={"kind": c.kind, **await item(c.kind, c.item, "item")}, **await folder_field(c.folder, None))
        elif c.op == "createFolder":
            if not c.name or not c.name.strip():
                raise ToolError("It needs the folder's `name`.")
            op.update(label=c.name.strip(), documentation=c.documentation, ref=c.ref, xmiIdentifier=c.xmi_identifier)
            if c.parent is not None and str(c.parent).strip("/ "):
                op["parent"] = await folder_item(c.parent, "parent")
        elif c.op == "updateFolder":
            op["folder"] = await folder_item(c.folder, "folder")
            if c.name is not None:
                if not c.name.strip():
                    raise ToolError("A folder needs a name.")
                op["label"] = c.name.strip()
            if c.documentation is not None:
                op["documentation"] = cleared(c.documentation)
                explicit.add("documentation")
            if c.parent is not None:
                op["parent"] = await folder_item(c.parent, "parent") if str(c.parent).strip("/ ") else None
                explicit.add("parent")
            if len(op) == 2 and not explicit:
                raise ToolError("Nothing to change: give name, documentation or parent.")
        elif c.op in ("updateView", "deleteView"):
            op["view"] = await item("view", c.view, "view")
            if c.op == "updateView":
                if c.name is not None:
                    if not c.name.strip():
                        raise ToolError("A view needs a name.")
                    op["name"] = c.name.strip()
                if c.documentation is not None:
                    op["documentation"] = cleared(c.documentation)
                    explicit.add("documentation")
                if "name" not in op and not explicit:
                    raise ToolError("Nothing to change: give name or documentation.")
        elif c.op == "deleteFolder":
            op["folder"] = await folder_item(c.folder, "folder")
            if c.move_contents_to is not None:
                op["moveContentsTo"] = await folder_item(c.move_contents_to, "move_contents_to")
        if c.expected_version:
            op["expectedVersion"] = c.expected_version
        elif versions is not None and (target := _target_of(c, op)) is not None:
            if target not in versions:
                kind, item_id = target
                path = f"organizations/{item_id}" if kind == "folder" else f"{kind}s/{item_id}"
                versions[target] = (await api.get(f"/models/{model_id}/{path}")).get("version")
            op["expectedVersion"] = versions[target]
        return {k: v for k, v in op.items() if v is not None or k in explicit}

    def _target_of(c: Change, op: dict[str, Any]) -> tuple[str, int] | None:
        """The existing item a change is checked against (for properties and filing: the owner), or None."""
        found = {"updateElement": ("element", "element"), "deleteElement": ("element", "element"),
                 "updateRelationship": ("relationship", "relationship"),
                 "deleteRelationship": ("relationship", "relationship"),
                 "setProperty": (c.kind, "owner"), "removeProperty": (c.kind, "owner"), "fileItem": (c.kind, "item"),
                 "updateFolder": ("folder", "folder"), "deleteFolder": ("folder", "folder"),
                 "updateView": ("view", "view"), "deleteView": ("view", "view")}.get(c.op)
        if found is None:
            return None
        kind, field = found
        item_id = (op.get(field) or {}).get("id")
        return (kind, item_id) if item_id is not None and kind in ("element", "relationship", "view", "folder") else None

    # ------------------------------------------------------------ a new model (1.4.0)

    if ctx.permissions is None or "import" in ctx.permissions:
        @server.tool(annotations=WRITE)
        @compact
        async def create_model(
            name: Annotated[str, Field(description="The model's name.")],
            documentation: Annotated[str | None, Field(description="Its documentation.")] = None,
            folders: Annotated[bool, Field(description="Give it the top-level folders Archi gives a new model (Strategy, "
                                                       "Business, Application, …, Relations, Views), so that new "
                                                       "elements are filed by their layer.")] = True,
            xmi_identifier: XmiRef = None,
        ) -> dict[str, Any]:
            """Create a new, empty model, by default with Archi's top-level folders. Needs a key that may create
            models (the API's role admin). Then fill it with apply_changes or the other write tools, naming it by
            its id or name."""
            created = await api.post("/models", {"xmiIdentifier": xmi_identifier or new_identifier(), "name": name,
                                                 **({"documentation": documentation} if documentation else {})})
            made = []
            if folders:
                for order, label in enumerate(ARCHI_FOLDERS):
                    await api.post(f"/models/{created['id']}/organizations", {"label": label, "sortOrder": order})
                    made.append(label)
            model_info = {"id": created["id"], "name": created["name"]}
            record("create_model", model_info, {"kind": "model", "id": created["id"], "name": created["name"]},
                   {"folders": made})
            return {"created": {**model_info, "xmiIdentifier": created["xmiIdentifier"]}, "folders": made,
                    "revision": await revision(created["id"])}

    # ------------------------------------------------------------ created views (1.9.0, MCP-28)

    async def created_view(model_id: int, ref: Ref) -> dict:
        """The view to rename or delete. 1.14.0: the API decides whether a view of the model's source may be (3.23.0:
        on a model mastered here, not on one linked to a file)."""
        return await lookup.view(model_id, ref)

    @server.tool(annotations=UPDATE)
    @compact
    async def update_view(
        view: Annotated[Ref, Field(description="The view: id, XMI identifier or name.")],
        model: ModelRef = None,
        name: Annotated[str | None, Field(description="A new name.")] = None,
        documentation: Annotated[str | None, Field(description="New documentation; \"\" removes it.")] = None,
        expected_version: ExpectedVersion = None,
    ) -> dict[str, Any]:
        """Rename a view or change its documentation: a created view or recipe, or a view of the model's source on a
        model mastered here (on a model linked to a file it is changed in Archi). What a view shows and where is
        arranged in the ArchiMate Browser (propose_view makes a link to start one)."""
        m = await lookup.model(model)
        v = await created_view(m["id"], view)
        body: dict[str, Any] = {}
        if name is not None:
            if not name.strip():
                raise ToolError("A view needs a name.")
            body["name"] = name.strip()
        if documentation is not None:
            body["documentation"] = documentation or None
        if not body:
            raise ToolError("Nothing to change: give name or documentation.")
        try:
            updated = await api.put(f"/models/{m['id']}/views/{v['id']}", body, if_match=expected_version or v.get("version"))
        except ApiError as e:
            raise refused(e) from e
        before = {k: v.get(k) for k in body}
        record("update_view", m, {"kind": "view", "id": v["id"], "name": v.get("name")}, {"before": before, "after": body})
        return {"updated": {"id": updated["id"], "name": updated.get("name"), "version": updated.get("version")},
                "before": before, "revision": await revision(m["id"])}

    @server.tool(annotations=DELETE)
    @compact
    async def delete_view(
        view: Annotated[Ref, Field(description="The view: id, XMI identifier or name.")],
        model: ModelRef = None,
        expected_version: ExpectedVersion = None,
    ) -> dict[str, Any]:
        """Delete a view: a created view or recipe, or a view of the model's source on a model mastered here (on a
        model linked to a file it is deleted in Archi; a replace of the model from a file that has it brings it back).
        It cannot be undone: tell the user which view (its name, where it comes from, who made it) and ask first. The
        elements and relationships it showed stay."""
        m = await lookup.model(model)
        v = await created_view(m["id"], view)
        try:
            await api.delete(f"/models/{m['id']}/views/{v['id']}", if_match=expected_version or v.get("version"))
        except ApiError as e:
            raise refused(e) from e
        record("delete_view", m, {"kind": "view", "id": v["id"], "name": v.get("name")}, {"createdBy": v.get("createdBy")})
        return {"deleted": {"id": v["id"], "name": v.get("name"), "createdBy": v.get("createdBy")},
                "revision": await revision(m["id"])}

    # ------------------------------------------------------------ folders

    @server.tool(annotations=UPDATE)
    @compact
    async def file_item(
        item: Annotated[Ref, Field(description="The element, relationship or view (see `kind`).")],
        folder: Annotated[Ref, Field(description="The folder: id, path (\"Business/Processes\") or a name only one "
                                                 "folder has (browse_folders shows them).")],
        model: ModelRef = None,
        kind: ItemKind = "element",
    ) -> dict[str, Any]:
        """File an element, relationship or view in a folder: it moves there from where it was filed, or is filed
        for the first time."""
        m = await lookup.model(model)
        it = await item_of(m["id"], kind, item)
        node, path = await lookup.folder(m["id"], folder)
        base = f"/models/{m['id']}"
        places = await api.get(f"{base}/{kind}s/{it['id']}/folders")
        before = ["/".join(f.get("label") or "" for f in place) for place in places]
        # 1.12.0: one operation of the changes endpoint, checked against the item's version as read here (an
        # API with REQUIRE_IF_MATCH refuses a change that says none); it leaves every other folder
        await changes_call(m["id"], {"op": "fileItem", "item": {"kind": kind, "id": it["id"]}, "folderId": node["id"],
                                     "expectedVersion": it.get("version")})
        summary = {"kind": kind, "id": it["id"], "name": it.get("name")}
        record("file_item", m, summary, {"before": before, "after": "/".join(path)})
        return {"item": summary, "folder": "/".join(path), "previously": before, "revision": await revision(m["id"])}

    async def siblings(model_id: int, parent: dict | None) -> list[dict]:
        """What is directly below `parent` (folders and items), or the top-level folders."""
        if parent is None:
            return await lookup.folder_tree(model_id)
        return (await api.get(f"/models/{model_id}/organizations/{parent['id']}")).get("children", [])

    async def parent_of(model_id: int, parent: Ref | None) -> tuple[dict | None, tuple[str, ...]]:
        """The folder named, or (None, ()) for the top level ("/")."""
        if parent is None or not str(parent).strip("/ "):
            return None, ()
        return await lookup.folder(model_id, parent)

    async def next_order(model_id: int, parent: dict | None) -> int:
        return max((c.get("sortOrder", 0) for c in await siblings(model_id, parent)), default=-1) + 1

    async def refuse_twin(model_id: int, label: str, parent: dict | None, path: tuple[str, ...],
                          but: int | None = None) -> None:
        """Two folders of one name side by side would make the path ambiguous."""
        for node in await siblings(model_id, parent):
            if node["id"] != but and (node.get("label") or "").strip().casefold() == label.strip().casefold():
                raise ToolError(f"There is a folder \"{'/'.join(path + (node.get('label') or '',))}\" already "
                                f"(id {node['id']}).")

    def folder_summary(node: dict, path: tuple[str, ...]) -> dict[str, Any]:
        return {"kind": "folder", "id": node["id"], "name": path[-1]}

    @server.tool(annotations=WRITE)
    @compact
    async def create_folder(
        name: Annotated[str, Field(description="The folder's name.")],
        parent: Annotated[Ref | None, Field(
            description="The folder to create it in: id, path (\"Business/Processes\") or a name only one folder "
                        "has. Default: the top level.")] = None,
        model: ModelRef = None,
        documentation: Annotated[str | None, Field(description="Its documentation.")] = None,
    ) -> dict[str, Any]:
        """Create a folder, after its parent's other sub-folders. A folder of the same name in the same place is
        refused."""
        m = await lookup.model(model)
        if not name.strip():
            raise ToolError("A folder needs a name.")
        node, path = await parent_of(m["id"], parent)
        await refuse_twin(m["id"], name, node, path)
        created = await api.post(f"/models/{m['id']}/organizations", {
            "label": name.strip(), "xmiIdentifier": new_identifier(), "sortOrder": await next_order(m["id"], node),
            **({"parentId": node["id"]} if node else {}), **({"documentation": documentation} if documentation else {})})
        path = path + (created["label"],)
        record("create_folder", m, folder_summary(created, path), {"path": "/".join(path)})
        return {"created": {"id": created["id"], "path": "/".join(path)}, "revision": await revision(m["id"])}

    @server.tool(annotations=UPDATE)
    @compact
    async def update_folder(
        folder: Annotated[Ref, Field(description="The folder: id, path (\"Business/Processes\") or a name only one "
                                                 "folder has.")],
        model: ModelRef = None,
        name: Annotated[str | None, Field(description="A new name.")] = None,
        documentation: Annotated[str | None, Field(description="New documentation; \"\" removes it.")] = None,
        parent: Annotated[Ref | None, Field(
            description="Move it, with everything in it, into this folder (id, path or name); \"/\" moves it to the "
                        "top level.")] = None,
        expected_version: Annotated[str | None, Field(description=(
            "The folder's `version` as browse_folders gave it; refused if someone changed it since."))] = None,
    ) -> dict[str, Any]:
        """Rename a folder, change its documentation, or move it with its contents into another folder. Give only
        what changes."""
        m = await lookup.model(model)
        node, path = await lookup.folder(m["id"], folder)
        if name is not None and not name.strip():
            raise ToolError("A folder needs a name.")
        body: dict[str, Any] = {}
        if documentation is not None:
            body["documentation"] = documentation or None
        if parent is not None:
            target, target_path = await parent_of(m["id"], parent)
            if target is not None and target_path[:len(path)] == path:
                raise ToolError("A folder cannot move into itself or one of its own sub-folders.")
            body.update(parentId=target["id"] if target else None, sortOrder=await next_order(m["id"], target))
        else:
            target = (await lookup.folder(m["id"], node["parentId"]))[0] if node.get("parentId") else None
            target_path = path[:-1]
        label = name.strip() if name is not None else path[-1]
        if name is not None:
            body["label"] = label
        if not body:
            raise ToolError("Nothing to change: give name, documentation or parent.")
        if "label" in body or "parentId" in body:
            await refuse_twin(m["id"], label, target, target_path, but=node["id"])
        try:
            await api.put(f"/models/{m['id']}/organizations/{node['id']}", body,
                          if_match=expected_version or node.get("version"))
        except ApiError as e:
            raise refused(e) from e
        before = {"path": "/".join(path), "documentation": node.get("documentation")}
        after = {"path": "/".join(target_path + (label,)),
                 **({"documentation": body["documentation"]} if "documentation" in body else {})}
        record("update_folder", m, folder_summary(node, path), {"before": before, "after": after})
        return {"updated": {"id": node["id"], "path": after["path"]}, "before": before,
                "revision": await revision(m["id"])}

    @server.tool(annotations=DELETE)
    @compact
    async def delete_folder(
        folder: Annotated[Ref, Field(description="The folder: id, path (\"Business/Processes\") or a name only one "
                                                 "folder has.")],
        model: ModelRef = None,
        move_contents_to: Annotated[Ref | None, Field(
            description="For a folder that is not empty: first move its sub-folders and what is filed in it into "
                        "this folder (id, path or name).")] = None,
        expected_version: Annotated[str | None, Field(description=(
            "The folder's `version` as browse_folders gave it; refused if someone changed it since."))] = None,
    ) -> dict[str, Any]:
        """Delete a folder. Only an empty one, unless move_contents_to says where its sub-folders and items go.
        Elements, relationships and views are never deleted with a folder. Where the contents go is the user's
        decision: unless they said, ask them, and do not choose a folder yourself."""
        m = await lookup.model(model)
        node, path = await lookup.folder(m["id"], folder)
        counts = node.get("counts", {})
        held = {k: counts[k] for k in ("folders", "elements", "relationships", "views") if counts.get(k)}
        moved: dict[str, Any] = {}
        operation: dict[str, Any] = {"op": "deleteFolder", "folder": {"id": node["id"]},
                                     "expectedVersion": expected_version or node.get("version")}
        if held:
            if move_contents_to is None:
                raise ToolError(f"\"{'/'.join(path)}\" is not empty: " + ", ".join(f"{v} {k}" for k, v in held.items())
                                + " at any depth. Ask the user where they should go (do not choose yourself), "
                                "then call again with move_contents_to.")
            target, target_path = await parent_of(m["id"], move_contents_to)
            if target is None:
                raise ToolError("Name a folder for move_contents_to: items cannot be filed at the top level.")
            if target_path[:len(path)] == path:
                raise ToolError("Its contents cannot move into the folder itself or one of its sub-folders.")
            children = (await api.get(f"/models/{m['id']}/organizations/{node['id']}")).get("children", [])
            for c in children:
                if c.get("label") is not None:
                    await refuse_twin(m["id"], c["label"], target, target_path)
            operation["moveContentsTo"] = {"id": target["id"]}
            moved = {"to": "/".join(target_path), **held}
        # 1.12.0: the move and the delete in one transaction, checked against the folder's version
        await changes_call(m["id"], operation)
        record("delete_folder", m, folder_summary(node, path), {"path": "/".join(path), **({"moved": moved} if moved else {})})
        return {"deleted": {"id": node["id"], "path": "/".join(path)}, **({"contentsMoved": moved} if moved else {}),
                "revision": await revision(m["id"])}

    # ------------------------------------------------------------ the model and its property definitions (1.6.0)

    if ctx.permissions is None or "import" in ctx.permissions:
        @server.tool(annotations=UPDATE)
        @compact
        async def update_model(
            model: ModelRef = None,
            name: Annotated[str | None, Field(description="A new name.")] = None,
            documentation: Annotated[str | None, Field(description="New documentation; \"\" removes it.")] = None,
            version: Annotated[str | None, Field(description="A new version label; \"\" removes it.")] = None,
        ) -> dict[str, Any]:
            """Change the model's name, documentation or version label. Give only what changes. Needs a key that may
            change models (the API's role admin). Its properties: set_property with kind=model."""
            m = await lookup.model(model)
            body: dict[str, Any] = {}
            if name is not None:
                if not name.strip():
                    raise ToolError("A model needs a name.")
                body["name"] = name.strip()
            for key, value in (("documentation", documentation), ("version", version)):
                if value is not None:
                    body[key] = value or None
            if not body:
                raise ToolError("Nothing to change: give name, documentation or version.")
            full = await api.get(f"/models/{m['id']}")
            try:  # the model's version is its revision (API 3.12.0)
                await api.put(f"/models/{m['id']}", body, if_match=str(full.get("revision")))
            except ApiError as e:
                raise refused(e) from e
            before = {k: full.get(k) for k in body}
            record("update_model", m, {"kind": "model", "id": m["id"], "name": m.get("name")},
                   {"before": before, "after": body})
            return {"updated": {"id": m["id"], **body}, "before": before, "revision": await revision(m["id"])}

    async def property_definition(model_id: int, name: str) -> dict:
        defs = await api.get(f"/models/{model_id}/property-definitions", limit=1000)
        defs = defs.get("items", defs) if isinstance(defs, dict) else defs
        same = [d for d in defs if (d.get("name") or "") == name] or \
               [d for d in defs if (d.get("name") or "").casefold() == name.strip().casefold()]
        if not same:
            raise ToolError(f"The model has no property \"{name}\". model_overview lists the properties in use.")
        if len(same) > 1:
            raise ToolError(f"\"{name}\" names {len(same)} property definitions (ids "
                            + ", ".join(str(d["id"]) for d in same) + "); give the exact name.")
        return same[0]

    async def values_of(model_id: int, definition_id: int) -> dict[str, int]:
        """How many values the definition has, by kind of owner."""
        counts = {}
        for owner in ("element", "relationship", "view", "model"):
            for entry in await api.get(f"/models/{model_id}/properties/index", owner=owner, maxValues=0):
                if entry.get("definitionId") == definition_id:
                    counts[owner] = entry.get("count", 0)
        return counts

    @server.tool(annotations=UPDATE)
    @compact
    async def update_property_definition(
        property: Annotated[str, Field(description="The property's name, as model_overview lists it.")],
        model: ModelRef = None,
        name: Annotated[str | None, Field(description="A new name, for every value it has.")] = None,
        data_type: Annotated[DataType | None, Field(description="A new data type: string, boolean, currency, date, "
                                                                "time or number.")] = None,
    ) -> dict[str, Any]:
        """Rename a property, or change its data type, for all its values at once. Renaming onto a name the model
        has already is refused: the two would be hard to tell apart."""
        m = await lookup.model(model)
        d = await property_definition(m["id"], property)
        body: dict[str, Any] = {}
        if name is not None:
            if not name.strip():
                raise ToolError("A property needs a name.")
            defs = await api.get(f"/models/{m['id']}/property-definitions", limit=1000)
            defs = defs.get("items", defs) if isinstance(defs, dict) else defs
            if any(x["id"] != d["id"] and (x.get("name") or "").casefold() == name.strip().casefold() for x in defs):
                raise ToolError(f"The model has a property \"{name.strip()}\" already.")
            body["name"] = name.strip()
        if data_type is not None:
            body["dataType"] = data_type
        if not body:
            raise ToolError("Nothing to change: give name or data_type.")
        try:
            await api.put(f"/models/{m['id']}/property-definitions/{d['id']}", body, if_match=d.get("version"))
        except ApiError as e:
            raise refused(e) from e
        before = {"name": d.get("name"), "dataType": d.get("dataType")}
        record("update_property_definition", m, {"kind": "propertyDefinition", "id": d["id"], "name": d.get("name")},
               {"before": before, "after": body})
        return {"updated": {"id": d["id"], **before, **body}, "before": before, "values": await values_of(m["id"], d["id"]),
                "revision": await revision(m["id"])}

    @server.tool(annotations=DELETE)
    @compact
    async def delete_property_definition(
        property: Annotated[str, Field(description="The property's name, as model_overview lists it.")],
        model: ModelRef = None,
        with_values: Annotated[bool, Field(description="Also when it still has values: they are deleted with it. "
                                                       "Only when the user agreed.")] = False,
    ) -> dict[str, Any]:
        """Delete a property definition. One that still has values is refused first with how many: tell the user
        and ask, and call again with with_values=true only when they agree."""
        m = await lookup.model(model)
        d = await property_definition(m["id"], property)
        counts = await values_of(m["id"], d["id"])
        if counts and not with_values:
            raise ToolError(f"\"{d.get('name')}\" has values: " + ", ".join(f"{v} on {k}s" for k, v in counts.items())
                            + ". Tell the user and ask; only when they agree, call again with with_values=true.")
        try:
            await api.delete(f"/models/{m['id']}/property-definitions/{d['id']}", if_match=d.get("version"))
        except ApiError as e:
            raise refused(e) from e
        record("delete_property_definition", m, {"kind": "propertyDefinition", "id": d["id"], "name": d.get("name")},
               {"values": counts})
        return {"deleted": {"id": d["id"], "name": d.get("name"), "dataType": d.get("dataType")},
                "valuesDeleted": counts, "revision": await revision(m["id"])}
