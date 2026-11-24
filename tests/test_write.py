"""MCP-15: the write tools (D11 to D21), against the real API, each test on a model of its own."""

from __future__ import annotations

import json
import uuid

import pytest
from mcp import Client

from app.server import build_server

from .api_server import ADMIN_KEY, EDITOR_KEY, READER_KEY
from .conftest import make_settings

pytestmark = pytest.mark.anyio

WRITE_TOOLS = {"create_element", "update_element", "delete_element", "create_relationship", "update_relationship",
               "delete_relationship", "set_property", "remove_property", "file_item", "apply_changes",
               "create_folder", "update_folder", "delete_folder", "update_property_definition",
               "delete_property_definition", "update_view", "delete_view"}


def _admin(api, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    return api.call(method, "/api/v2" + path, data=data, content_type="application/json" if data else None)


@pytest.fixture
def model(api):
    """A new, empty model with the top-level folders Archi makes (no Motivation folder), and a sub-folder."""
    name = f"Write test {uuid.uuid4().hex[:8]}"
    m = _admin(api, "POST", "/models", {"xmiIdentifier": f"id-{uuid.uuid4().hex}", "name": name})
    folders = {}
    for i, label in enumerate(("Business", "Application", "Relations")):
        folders[label] = _admin(api, "POST", f"/models/{m['id']}/organizations", {"label": label, "sortOrder": i})["id"]
    folders["Business/Processes"] = _admin(api, "POST", f"/models/{m['id']}/organizations",
                                           {"label": "Processes", "parentId": folders["Business"]})["id"]
    m["folders"] = folders
    return m


@pytest.fixture
async def call(api, tmp_path):
    settings = make_settings(api_url=api.url, api_key=EDITOR_KEY, allow_write=True,
                             change_log=str(tmp_path / "changes.log"))
    async with Client(build_server(settings, writable=True, key_name="mcp-tests-editor")) as client:
        async def run(tool: str, **arguments):
            result = await client.call_tool(tool, arguments)
            assert not result.is_error, result.content[0].text
            return result.structured_content

        async def fails(tool: str, **arguments) -> str:
            result = await client.call_tool(tool, arguments)
            assert result.is_error, result.structured_content
            return result.content[0].text
        run.fails = fails
        run.client = client
        run.log = tmp_path / "changes.log"
        yield run


async def test_write_tools_are_offered_only_when_writing_is_on(api):
    reading = make_settings(api_url=api.url, api_key=READER_KEY)
    async with Client(build_server(reading)) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert not names & WRITE_TOOLS
        assert "only reads" in c.instructions
    writing = make_settings(api_url=api.url, api_key=EDITOR_KEY, allow_write=True, change_log="")
    async with Client(build_server(writing, writable=True, permissions=["read", "write"])) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert WRITE_TOOLS <= set(tools)
        assert "search first" in c.instructions and "Ask the user before every delete" in c.instructions
        assert "update_model" not in tools and "create_model" not in tools, "only with a key that may change models"
        assert tools["delete_element"].annotations.destructive_hint is True
        assert tools["create_element"].annotations.read_only_hint is False
        assert tools["create_element"].annotations.destructive_hint is False


async def test_create_element_files_it_in_its_layer_and_records_it(call, model):
    answer = await call("create_element", model=model["id"], type="BusinessProcess", name="Handle Order",
                        documentation="From order to delivery.", properties={"owner": "Sales"})
    created = answer["created"]
    assert (created["type"], created["name"]) == ("BusinessProcess", "Handle Order")
    assert created["xmiIdentifier"].startswith("id-") and len(created["xmiIdentifier"]) == 35
    assert answer["folder"] == "Business"
    assert answer["revision"] > model["revision"]
    element = await call("get_element", model=model["id"], element=created["id"])
    assert element["properties"] == {"owner": "Sales"}
    assert element["folders"] == ["Business"]
    # the record of changes (D20)
    [line] = call.log.read_text(encoding="utf-8").splitlines()
    entry = json.loads(line)
    assert (entry["tool"], entry["key"], entry["model"]["id"], entry["item"]["id"]) == (
        "create_element", "mcp-tests-editor", model["id"], created["id"])
    # a second one of the same type and name: created, with a warning (D19)
    again = await call("create_element", model=model["id"], type="BusinessProcess", name="handle order ",
                       folder="Business/Processes")
    assert again["folder"] == "Business/Processes"
    assert "Likely a duplicate" in again["warnings"][0] and str(created["id"]) in again["warnings"][0]


async def test_an_element_whose_layer_has_no_folder_is_filed_nowhere(call, model):
    answer = await call("create_element", model=model["id"], type="Goal", name="Faster delivery")
    assert answer["folder"] is None
    assert "no top-level folder 'Motivation'" in answer["warnings"][0]
    assert "folder" in await call.fails("create_element", model=model["id"], type="Goal", name="x", folder="Nowhere")


async def test_relationships_follow_archimate_rules(call, model):
    app = (await call("create_element", model=model["id"], type="ApplicationComponent", name="CRM"))["created"]
    process = (await call("create_element", model=model["id"], type="BusinessProcess", name="Sell"))["created"]
    serving = await call("create_relationship", model=model["id"], type="Serving", source="CRM", target=process["id"])
    assert serving["folder"] == "Relations"
    assert serving["between"] == "CRM -> Sell"
    # the API's default RELATIONSHIP_RULES refuses what ArchiMate does not allow; the hint names the tool
    text = await call.fails("create_relationship", model=model["id"], type="Composition", source=process["id"],
                            target=app["id"])
    assert "RELATIONSHIP_RULES" in text and "allowed_relationships" in text
    # an association onto the relationship
    note = (await call("create_element", model=model["id"], type="BusinessActor", name="Clerk"))["created"]
    on = await call("create_relationship", model=model["id"], type="Association", source=note["id"],
                    target_relationship=serving["created"]["id"])
    assert on["between"].endswith(f"relationship {serving['created']['id']}")
    duplicate = await call("create_relationship", model=model["id"], type="Serving", source="CRM", target="Sell")
    assert "Likely a duplicate" in duplicate["warnings"][0]
    assert "exactly one source" in await call.fails("create_relationship", model=model["id"], type="Serving",
                                                     target="Sell")


async def test_update_element_and_relationship(call, model):
    actor = (await call("create_element", model=model["id"], type="BusinessActor", name="Clerk"))["created"]
    role = (await call("create_element", model=model["id"], type="BusinessRole", name="Cashier"))["created"]
    rel = (await call("create_relationship", model=model["id"], type="Assignment", source=actor["id"],
                      target=role["id"]))["created"]
    renamed = await call("update_element", model=model["id"], element=actor["id"], name="Shop clerk", documentation="Sells.")
    assert renamed["updated"]["name"] == "Shop clerk" and renamed["before"] == {"name": "Clerk", "documentation": None}
    # a new type that breaks its relationship is refused by the API
    text = await call.fails("update_element", model=model["id"], element=role["id"], type="Goal")
    assert "RELATIONSHIP_NOT_ALLOWED" in text or "not allowed" in text
    assert "Nothing to change" in await call.fails("update_element", model=model["id"], element=actor["id"])
    named = await call("update_relationship", model=model["id"], relationship=rel["id"], name="plays")
    assert named["updated"]["name"] == "plays"
    assert "allowed_relationships" in await call.fails("update_relationship", model=model["id"],
                                                        relationship=rel["id"], type="Composition")


async def test_properties(call, model):
    e = (await call("create_element", model=model["id"], type="ApplicationComponent", name="ERP"))["created"]
    first = await call("set_property", model=model["id"], item=e["id"], name="lifecycle", value="current")
    assert first["previous"] is None
    second = await call("set_property", model=model["id"], item="ERP", name="lifecycle", value="retiring")
    assert second["previous"] == "current"
    await call("set_property", model=model["id"], item=e["id"], name="name", value="PodnikovÃ½ systÃ©m", lang="cs")
    assert (await call("get_element", model=model["id"], element=e["id"]))["properties"] == {
        "lifecycle": "retiring", "name": "PodnikovÃ½ systÃ©m (cs)"}
    removed = await call("remove_property", model=model["id"], item=e["id"], name="lifecycle")
    assert removed["removed"] == [{"value": "retiring"}]
    assert "no property" in await call.fails("remove_property", model=model["id"], item=e["id"], name="lifecycle")


async def test_file_item_moves_it(call, model):
    p = (await call("create_element", model=model["id"], type="BusinessProcess", name="Ship"))["created"]
    moved = await call("file_item", model=model["id"], item=p["id"], folder="Processes")
    assert (moved["previously"], moved["folder"]) == (["Business"], "Business/Processes")
    again = await call("file_item", model=model["id"], item=p["id"], folder=model["folders"]["Business"])
    assert (again["previously"], again["folder"]) == (["Business/Processes"], "Business")


async def test_delete_needs_cascade_for_an_element_with_relationships(call, model):
    a = (await call("create_element", model=model["id"], type="ApplicationComponent", name="Old CRM"))["created"]
    b = (await call("create_element", model=model["id"], type="ApplicationService", name="Customer data"))["created"]
    rel = (await call("create_relationship", model=model["id"], type="Realization", source=a["id"], target=b["id"]))["created"]
    text = await call.fails("delete_element", model=model["id"], element=a["id"])
    assert "1 relationship(s)" in text and "cascade=true" in text
    gone = await call("delete_element", model=model["id"], element=a["id"], cascade=True)
    assert gone["deleted"]["id"] == a["id"]
    assert [r["id"] for r in gone["alsoDeleted"]["relationships"]["items"]] == [rel["id"]]
    alone = await call("delete_element", model=model["id"], element=b["id"])  # nothing attached: no cascade needed
    assert alone["alsoDeleted"]["relationships"]["total"] == 0
    tools = [json.loads(line)["tool"] for line in call.log.read_text(encoding="utf-8").splitlines()]
    assert tools.count("delete_element") == 2


async def test_delete_relationship_lists_what_was_attached(call, model):
    a = (await call("create_element", model=model["id"], type="BusinessActor", name="A"))["created"]
    b = (await call("create_element", model=model["id"], type="BusinessRole", name="B"))["created"]
    rel = (await call("create_relationship", model=model["id"], type="Assignment", source=a["id"], target=b["id"]))["created"]
    on = (await call("create_relationship", model=model["id"], type="Association", source=a["id"],
                     target_relationship=rel["id"]))["created"]
    gone = await call("delete_relationship", model=model["id"], relationship=rel["id"])
    assert [r["id"] for r in gone["alsoDeleted"]["attachedRelationships"]["items"]] == [on["id"]]


async def test_a_key_that_may_not_write_is_refused_by_the_api(api, model):
    settings = make_settings(api_url=api.url, api_key=READER_KEY, allow_write=True, change_log="")
    async with Client(build_server(settings, writable=True)) as c:
        result = await c.call_tool("create_element", {"model": model["id"], "type": "BusinessActor", "name": "X"})
    assert result.is_error
    assert "may not do this" in result.content[0].text


async def test_apply_changes_builds_a_piece_of_a_model_in_one_transaction(call, model):
    old = (await call("create_element", model=model["id"], type="ApplicationComponent", name="Old CRM"))["created"]
    answer = await call("apply_changes", model=model["id"], changes=[
        {"op": "createElement", "ref": "crm", "type": "ApplicationComponent", "name": "CRM", "properties": {"owner": "Sales"}},
        {"op": "createElement", "ref": "sell", "type": "BusinessProcess", "name": "Sell", "folder": "Processes"},
        {"op": "createRelationship", "ref": "serves", "type": "Serving", "source": "@crm", "target": "@sell", "name": "supports"},
        {"op": "updateElement", "element": "Old CRM", "name": "Legacy CRM", "documentation": "Retiring."},
        {"op": "setProperty", "item": "@serves", "kind": "relationship", "name": "since", "value": "2026"},
    ])
    assert answer["applied"] == 5
    assert answer["byOperation"] == {"createElement": 2, "createRelationship": 1, "updateElement": 1, "setProperty": 1}
    crm, sell, serves = (r["id"] for r in answer["results"]["items"][:3])
    assert answer["results"]["items"][3]["before"] == {"name": "Old CRM", "documentation": None}
    element = await call("get_element", model=model["id"], element=crm)
    assert element["folders"] == ["Application"] and element["properties"] == {"owner": "Sales"}, "default folder of its layer"
    assert (await call("get_element", model=model["id"], element=sell))["folders"] == ["Business/Processes"]
    rel = await call("get_relationship", model=model["id"], relationship=serves)
    assert rel["name"] == "supports" and rel["properties"] == {"since": "2026"}
    assert (await call("get_element", model=model["id"], element=old["id"]))["name"] == "Legacy CRM"
    lines = [json.loads(line) for line in call.log.read_text(encoding="utf-8").splitlines()]
    assert [entry["tool"] for entry in lines].count("apply_changes") == 5, "one record per change"


async def test_apply_changes_is_all_or_nothing(call, model):
    rev = (await call("create_element", model=model["id"], type="Goal", name="Faster"))["revision"]
    text = await call.fails("apply_changes", model=model["id"], changes=[
        {"op": "createElement", "ref": "a", "type": "BusinessActor", "name": "Clerk"},
        {"op": "createRelationship", "type": "Composition", "source": "Faster", "target": "@a"},
    ])
    assert "Operation 2 (createRelationship)" in text and "allowed_relationships" in text
    found = await call("search", model=model["id"], q="Clerk")
    assert found["elements"]["total"] == 0, "the first change was undone too"
    text = await call.fails("apply_changes", model=model["id"], expected_revision=rev - 1,
                            changes=[{"op": "createElement", "type": "BusinessActor", "name": "X"}])
    assert "412" in text and "changed since it was read" in text
    assert "Change 1 (createElement): It needs `type`" in await call.fails(
        "apply_changes", model=model["id"], changes=[{"op": "createElement", "name": "X"}])
    assert "Change 2 (updateElement)" in await call.fails("apply_changes", model=model["id"], changes=[
        {"op": "createElement", "type": "BusinessActor", "name": "Y"}, {"op": "updateElement", "element": "Nobody here", "name": "Z"}])


async def test_create_model_needs_a_key_that_may_create_models(api, tmp_path):
    editor = make_settings(api_url=api.url, api_key=EDITOR_KEY, allow_write=True, change_log="")
    async with Client(build_server(editor, writable=True, permissions=["read", "write"])) as c:
        assert "create_model" not in {t.name for t in (await c.list_tools()).tools}
    admin = make_settings(api_url=api.url, api_key=ADMIN_KEY, allow_write=True, change_log=str(tmp_path / "c.log"))
    async with Client(build_server(admin, writable=True, permissions=["read", "write", "import", "deleteModel"])) as c:
        result = await c.call_tool("create_model", {"name": f"New model {uuid.uuid4().hex[:6]}", "documentation": "Empty."})
        assert not result.is_error, result.content[0].text
        made = result.structured_content
        assert made["folders"][:3] == ["Strategy", "Business", "Application"] and made["folders"][-2:] == ["Relations", "Views"]
        added = (await c.call_tool("create_element", {"model": made["created"]["id"], "type": "Capability", "name": "Sell"})).structured_content
        assert added["folder"] == "Strategy", "filed by its layer at once"


async def test_folders_are_created_renamed_moved_and_deleted(call, model):
    made = await call("create_folder", model=model["id"], name="Data", parent="Application", documentation="Stores.")
    assert made["created"]["path"] == "Application/Data"
    assert "already" in await call.fails("create_folder", model=model["id"], name="data", parent="Application")
    top = (await call("create_folder", model=model["id"], name="Archive"))["created"]
    assert top["path"] == "Archive"
    store = (await call("create_element", model=model["id"], type="DataObject", name="Order", folder="Application/Data"))
    assert store["folder"] == "Application/Data"
    renamed = await call("update_folder", model=model["id"], folder="Application/Data", name="Data objects")
    assert renamed["updated"]["path"] == "Application/Data objects" and renamed["before"]["path"] == "Application/Data"
    moved = await call("update_folder", model=model["id"], folder="Data objects", parent="Business/Processes")
    assert moved["updated"]["path"] == "Business/Processes/Data objects"
    assert (await call("get_element", model=model["id"], element=store["created"]["id"]))["folders"] == [
        "Business/Processes/Data objects"], "the contents move with the folder"
    assert "itself" in await call.fails("update_folder", model=model["id"], folder="Business",
                                        parent="Business/Processes/Data objects")
    assert (await call("update_folder", model=model["id"], folder="Data objects", parent="/"))["updated"]["path"] == "Data objects"
    text = await call.fails("delete_folder", model=model["id"], folder="Data objects")
    assert "not empty" in text and "1 elements" in text
    gone = await call("delete_folder", model=model["id"], folder="Data objects", move_contents_to="Archive")
    assert gone["contentsMoved"] == {"to": "Archive", "elements": 1}
    assert (await call("get_element", model=model["id"], element=store["created"]["id"]))["folders"] == ["Archive"]
    assert (await call("delete_folder", model=model["id"], folder="Business/Processes"))["deleted"]["path"] == "Business/Processes"
    lines = [json.loads(line)["tool"] for line in call.log.read_text(encoding="utf-8").splitlines()]
    assert lines.count("create_folder") == 2 and lines.count("update_folder") == 3 and lines.count("delete_folder") == 2


async def test_apply_changes_makes_folders_and_files_into_them(call, model):
    answer = await call("apply_changes", model=model["id"], changes=[
        {"op": "createFolder", "ref": "data", "name": "Data", "parent": "Application", "documentation": "Stores."},
        {"op": "createElement", "ref": "order", "type": "DataObject", "name": "Order", "folder": "@data"},
        {"op": "createFolder", "ref": "old", "name": "Old", "parent": "@data"},
        {"op": "createElement", "type": "DataObject", "name": "Bill", "folder": "@old"},
        {"op": "updateFolder", "folder": "Business/Processes", "name": "Process areas", "documentation": ""},
        {"op": "createFolder", "name": "Archive"},
    ])
    assert answer["byOperation"] == {"createFolder": 3, "createElement": 2, "updateFolder": 1}
    order = answer["results"]["items"][1]["id"]
    assert (await call("get_element", model=model["id"], element=order))["folders"] == ["Application/Data"]
    assert (await call("get_element", model=model["id"], element="Bill"))["folders"] == ["Application/Data/Old"]
    tops = [f["name"] for f in (await call("browse_folders", model=model["id"]))["folders"]]
    assert "Archive" in tops and "Business" in tops
    moved = await call("apply_changes", model=model["id"], changes=[
        {"op": "updateFolder", "folder": "Application/Data/Old", "parent": "/"},
        {"op": "deleteFolder", "folder": "Application/Data", "move_contents_to": "Archive"},
    ])
    assert moved["results"]["items"][1]["moved"]["entries"] == 1
    assert (await call("get_element", model=model["id"], element=order))["folders"] == ["Archive"]
    assert (await call("get_element", model=model["id"], element="Bill"))["folders"] == ["Old"]
    text = await call.fails("apply_changes", model=model["id"], changes=[{"op": "createFolder", "name": "archive"}])
    assert "already" in text
    text = await call.fails("apply_changes", model=model["id"], changes=[{"op": "deleteFolder", "folder": "Archive"}])
    assert "not empty" in text


async def test_the_model_s_own_properties(call, model):
    done = await call("set_property", model=model["id"], kind="model", name="owner", value="EA team")
    assert done["previous"] is None and done["item"]["kind"] == "model"
    again = await call("set_property", model=model["id"], kind="model", name="owner", value="Architecture")
    assert again["previous"] == "EA team"
    removed = await call("remove_property", model=model["id"], kind="model", name="owner")
    assert removed["removed"] == [{"value": "Architecture"}]
    assert "needs `item`" in await call.fails("set_property", model=model["id"], name="x", value="y")


async def test_property_definitions_are_renamed_retyped_and_deleted(call, model):
    await call("create_element", model=model["id"], type="ApplicationComponent", name="ERP", properties={"cost": "10"})
    await call("set_property", model=model["id"], kind="model", name="reviewed", value="2026")
    renamed = await call("update_property_definition", model=model["id"], property="cost", name="yearly cost",
                         data_type="currency")
    assert renamed["before"] == {"name": "cost", "dataType": "string"}
    assert renamed["updated"]["name"] == "yearly cost" and renamed["values"] == {"element": 1}
    assert (await call("get_element", model=model["id"], element="ERP"))["properties"] == {"yearly cost": "10"}
    assert "already" in await call.fails("update_property_definition", model=model["id"], property="yearly cost",
                                         name="Reviewed")
    text = await call.fails("delete_property_definition", model=model["id"], property="yearly cost")
    assert "1 on elements" in text and "ask" in text
    gone = await call("delete_property_definition", model=model["id"], property="yearly cost", with_values=True)
    assert gone["valuesDeleted"] == {"element": 1}
    assert (await call("get_element", model=model["id"], element="ERP"))["properties"] == {}
    assert "no property" in await call.fails("delete_property_definition", model=model["id"], property="cost")


async def test_update_model_needs_a_key_that_may_change_models(api, model, tmp_path):
    admin = make_settings(api_url=api.url, api_key=ADMIN_KEY, allow_write=True, change_log=str(tmp_path / "c.log"))
    async with Client(build_server(admin, writable=True, permissions=["read", "write", "import", "deleteModel"])) as c:
        result = await c.call_tool("update_model", {"model": model["id"], "name": model["name"] + " (renamed)",
                                                    "documentation": "For tests."})
        assert not result.is_error, result.content[0].text
        assert result.structured_content["before"] == {"name": model["name"], "documentation": None}
    assert _admin(api, "GET", f"/models/{model['id']}")["name"] == model["name"] + " (renamed)"


async def test_deletes_tell_the_assistant_to_ask_first(call, model):
    a = (await call("create_element", model=model["id"], type="BusinessActor", name="Customer"))["created"]
    b = (await call("create_element", model=model["id"], type="BusinessRole", name="Buyer"))["created"]
    await call("create_relationship", model=model["id"], type="Assignment", source=a["id"], target=b["id"])
    assert "ask" in await call.fails("delete_element", model=model["id"], element=a["id"])
    await call("create_element", model=model["id"], type="BusinessProcess", name="Sell", folder="Business/Processes")
    text = await call.fails("delete_folder", model=model["id"], folder="Business/Processes")
    assert "Ask the user where they should go" in text


async def test_model_history_names_the_key_and_this_server(call, model):
    e = (await call("create_element", model=model["id"], type="BusinessActor", name="Clerk"))["created"]
    await call("update_element", model=model["id"], element=e["id"], name="Senior clerk")
    answer = await call("model_history", model=model["id"], item=e["id"])
    changes = answer["changes"]["items"]
    assert [c["op"] for c in changes] == ["update", "create"]
    assert changes[0]["user"] == "mcp-tests-editor" and changes[0]["client"].startswith("ArchiMate MCP ")
    assert changes[0]["before"] == {"name": "Clerk"} and changes[0]["after"] == {"name": "Senior clerk"}
    everything = await call("model_history", model=model["id"], user="mcp-tests-editor", limit=2)
    assert everything["changes"]["truncated"] is True


async def test_model_history_is_for_keys_that_may_write(api):
    reading = make_settings(api_url=api.url, api_key=READER_KEY)
    async with Client(build_server(reading, permissions=["read"])) as c:
        assert "model_history" not in {t.name for t in (await c.list_tools()).tools}


# ------------------------------------------------------------ 1.8.0: safe concurrent writes (API 3.12.0)

async def test_a_change_based_on_a_stale_version_is_refused_with_who_changed_it(api, call, model):
    made = (await call("create_element", model=model["id"], type="BusinessProcess", name="Order Handling"))["created"]
    seen = await call("get_element", model=model["id"], element=made["id"])
    assert len(seen["version"]) == 16
    _admin(api, "PUT", f"/models/{model['id']}/elements/{made['id']}", {"name": "Order handling process"})
    text = await call.fails("update_element", model=model["id"], element=made["id"], documentation="Jana's text",
                            expected_version=seen["version"])
    assert "412" in text and "changed since it was read" in text
    assert "Last change by default" in text and "'Order Handling' -> 'Order handling process'" in text
    assert "tell the user" in text and "Nothing was changed" in text
    assert (await call("get_element", model=model["id"], element=made["id"]))["documentation"] is None
    for tool, args in (("delete_element", {"element": made["id"]}),
                       ("set_property", {"item": made["id"], "name": "Owner", "value": "Sales"})):
        assert "changed since it was read" in await call.fails(tool, model=model["id"], expected_version=seen["version"], **args), tool
    # without expected_version: the version read in the same call
    done = await call("update_element", model=model["id"], element=made["id"], documentation="Jana's text")
    assert done["updated"]["id"] == made["id"]
    now = (await call("get_element", model=model["id"], element=made["id"]))["version"]
    await call("set_property", model=model["id"], item=made["id"], name="Owner", value="Sales", expected_version=now)
    after = await call("get_element", model=model["id"], element=made["id"])
    assert after["properties"] == {"Owner": "Sales"} and after["version"] != now, "a property is part of the version"
    stale = await call.fails("remove_property", model=model["id"], item=made["id"], name="Owner", expected_version=now)
    assert "changed since it was read" in stale
    await call("remove_property", model=model["id"], item=made["id"], name="Owner", expected_version=after["version"])


async def test_apply_changes_with_a_stale_version_applies_nothing(api, call, model):
    made = (await call("create_element", model=model["id"], type="BusinessActor", name="Clerk"))["created"]
    seen = (await call("get_element", model=model["id"], element=made["id"]))["version"]
    _admin(api, "PUT", f"/models/{model['id']}/elements/{made['id']}", {"documentation": "elsewhere"})
    text = await call.fails("apply_changes", model=model["id"], changes=[
        {"op": "createElement", "type": "BusinessRole", "name": "Seller"},
        {"op": "updateElement", "element": str(made["id"]), "name": "Senior clerk", "expected_version": seen}])
    assert "Operation 2 (updateElement)" in text and "changed since it was read" in text
    assert (await call("search", model=model["id"], query="Seller"))["elements"]["total"] == 0


async def test_versions_in_the_answers(call, model):
    a = (await call("create_element", model=model["id"], type="BusinessActor", name="A"))["created"]
    b = (await call("create_element", model=model["id"], type="BusinessRole", name="B"))["created"]
    r = (await call("create_relationship", model=model["id"], type="Assignment", source=a["id"], target=b["id"]))["created"]
    assert len((await call("get_relationship", model=model["id"], relationship=r["id"]))["version"]) == 16
    folder = await call("browse_folders", model=model["id"], folder="Business/Processes")
    assert len(folder["folder"]["version"]) == 16
    renamed = await call("update_folder", model=model["id"], folder="Business/Processes", name="Flows",
                         expected_version=folder["folder"]["version"])
    assert renamed["updated"]["path"] == "Business/Flows"
    stale = await call.fails("delete_folder", model=model["id"], folder="Business/Flows",
                             expected_version=folder["folder"]["version"])
    assert "changed since it was read" in stale and "Nothing was changed" in stale


# ---------------------------------------------------------------- MCP-28 (1.9.0): created views

async def test_created_views_are_renamed_and_deleted(call, model, api):
    a = _admin(api, "POST", f"/models/{model['id']}/elements",
               {"xmiIdentifier": f"id-{uuid.uuid4().hex}", "type": "BusinessActor", "name": "Customer"})
    v = _admin(api, "POST", f"/models/{model['id']}/views", {"name": "Mine", "content": {
        "nodes": [{"ref": "a", "elementId": a["id"], "x": 10, "y": 10, "w": 120, "h": 55}]}})
    listed = (await call("list_views", model=model["id"], origin="created"))["views"]["items"]
    assert [(x["name"], x["origin"]) for x in listed] == [("Mine", "created")]
    got = await call("get_view", model=model["id"], view=v["id"])
    assert got["origin"] == "created" and got["createdBy"], got
    assert [e["name"] for e in got["elements"]["items"]] == ["Customer"]

    renamed = await call("update_view", model=model["id"], view="Mine", name="Ours", expected_version=got["version"])
    assert renamed["updated"]["name"] == "Ours" and renamed["before"] == {"name": "Mine"}
    done = await call("apply_changes", model=model["id"], changes=[
        {"op": "updateView", "view": "Ours", "documentation": "For the review"}])
    assert done["applied"] == 1
    assert (await call("get_view", model=model["id"], view="Ours"))["documentation"] == "For the review"

    gone = await call("delete_view", model=model["id"], view="Ours")
    assert gone["deleted"]["name"] == "Ours"
    assert (await call("list_views", model=model["id"]))["views"]["total"] == 0
    tools = {t.name: t for t in (await call.client.list_tools()).tools}
    assert tools["delete_view"].annotations.destructive_hint is True
    assert "cannot be undone" in tools["delete_view"].description and "ask" in tools["delete_view"].description


async def test_a_view_of_the_source_is_renamed_and_deleted_on_a_model_mastered_here(call, api):
    """1.14.0 (API 3.23.0): renamed and deleted like any view; what it shows stays, as the source has it."""
    from .api_server import SYNTHETIC_MODEL

    mid = api.import_model("copy.xml", (api.api_dir / SYNTHETIC_MODEL).read_bytes())
    _admin(api, "PUT", f"/models/{mid}", {"name": f"Source views {uuid.uuid4().hex[:8]}"})  # not the synthetic model's name
    try:
        got = await call("get_view", model=mid, view="Overview")
        assert got["origin"] == "source"
        renamed = await call("update_view", model=mid, view="Overview", name="Our overview", expected_version=got["version"])
        assert renamed["updated"]["name"] == "Our overview"
        again = await call("get_view", model=mid, view="Our overview")
        assert again["elements"]["total"] == got["elements"]["total"], "what it shows stays"
        assert (await call("delete_view", model=mid, view="Our overview"))["deleted"]["name"] == "Our overview"
        assert not [v for v in (await call("list_views", model=mid))["views"]["items"] if v["name"] == "Our overview"]
        # what it shows is never changed here
        tools = {t.name: t for t in (await call.client.list_tools()).tools}
        assert "mastered here" in tools["update_view"].description and "mastered here" in tools["delete_view"].description
    finally:
        _admin(api, "DELETE", f"/models/{mid}")


async def test_a_recipe_says_what_it_is(call, model, api):
    """1.13.0 (API 3.22.0): a recipe is listed with its recipe; get_view says it has no drawing; it is renamed and deleted."""
    v = _admin(api, "POST", f"/models/{model['id']}/views", {"name": "All actors", "recipe": "#model=x&d=ty~BusinessActor"})
    listed = (await call("list_views", model=model["id"], origin="created"))["views"]["items"]
    assert [(x["name"], x["recipe"]) for x in listed] == [("All actors", "d=ty~BusinessActor")]
    got = await call("get_view", model=model["id"], view=v["id"])
    assert got["recipe"] == "d=ty~BusinessActor" and got["origin"] == "created" and "no drawing" in got["note"]
    assert "elements" not in got
    renamed = await call("update_view", model=model["id"], view="All actors", name="Actors", expected_version=got["version"])
    assert renamed["updated"]["name"] == "Actors"
    assert (await call("delete_view", model=model["id"], view="Actors"))["deleted"]["name"] == "Actors"


# ---------------------------------------------------------------- 1.10.0: where a model is mastered (BL-58)

async def test_the_master_of_a_model_and_a_refusal_on_a_linked_one(call, model, api):
    overview = (await call("model_overview", model=model["id"]))["model"]
    assert overview["master"] == "api" and "linkedTo" not in overview
    before = overview["editedSinceImport"]
    await call("create_element", model=model["id"], type="BusinessActor", name="Counted")
    assert (await call("model_overview", model=model["id"]))["model"]["editedSinceImport"] > before
    listed = {m["id"]: m for m in (await call("list_models"))["models"]}
    assert listed[model["id"]]["master"] == "api"

    # a model linked to a file: read-only here, and the refusal says what to do instead
    xml = (api.api_dir / "tests" / "fixtures" / "Basic_Model.xml").read_text(encoding="utf-8")
    path = api.tmp / "linked" / f"linked-{uuid.uuid4().hex[:8]}.xml"
    path.write_text(xml.replace('identifier="model-1"', f'identifier="id-{uuid.uuid4().hex}"', 1), encoding="utf-8")
    linked = _admin(api, "POST", "/models/linked", {"path": str(path)})["model"]["id"]
    try:
        overview = (await call("model_overview", model=linked))["model"]
        assert overview["master"] == "file" and "editedSinceImport" not in overview
        assert overview["linkedTo"]["path"] == str(path)
        listed = {m["id"]: m for m in (await call("list_models"))["models"]}
        assert listed[linked]["master"] == "file" and listed[linked]["linkedTo"]["path"] == str(path)
        message = await call.fails("create_element", model=linked, type="BusinessActor", name="Refused")
        assert "409" in message and "mastered by its file" in message and "Archi" in message, message
        assert "unlink" in message and "propose_view" in message
    finally:
        _admin(api, "DELETE", f"/models/{linked}/link")
        _admin(api, "DELETE", f"/models/{linked}")
