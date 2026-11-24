"""
1.12.0: the write tools against an API with REQUIRE_IF_MATCH=true, which refuses (428) a change of an
existing item that says no version. None of the calls here gives expected_version: each tool sends the
version it reads just before the write. The rest of the suite runs against such an API too, unless
ARCHIMATE_TEST_REQUIRE_IF_MATCH=false; these tests always do.
"""

from __future__ import annotations

import json
import uuid

import pytest
from mcp import Client

from app.server import build_server

from .api_server import ADMIN_KEY, ApiNotAvailable, TestApi
from .conftest import make_settings

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def strict(api):
    """The suite's API when it requires a version, else one of its own that does."""
    if api.require_if_match:
        yield api
        return
    try:
        server = TestApi(require_if_match=True).start()
    except ApiNotAvailable as e:
        pytest.skip(str(e))
    yield server
    server.stop()


def _admin(api, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    return api.call(method, "/api/v2" + path, data=data, content_type="application/json" if data else None)


@pytest.fixture
def model(strict):
    m = _admin(strict, "POST", "/models", {"xmiIdentifier": f"id-{uuid.uuid4().hex}",
                                           "name": f"Strict test {uuid.uuid4().hex[:8]}"})
    for i, label in enumerate(("Business", "Application", "Relations", "Views")):
        _admin(strict, "POST", f"/models/{m['id']}/organizations", {"label": label, "sortOrder": i})
    yield m
    _admin(strict, "DELETE", f"/models/{m['id']}")  # the suite's API counts its models (test_tools)


@pytest.fixture
async def call(strict, tmp_path):
    # an admin key: update_model too
    settings = make_settings(api_url=strict.url, api_key=ADMIN_KEY, allow_write=True, change_log="")
    async with Client(build_server(settings, writable=True, key_name="default")) as client:
        async def run(tool: str, **arguments):
            result = await client.call_tool(tool, arguments)
            assert not result.is_error, f"{tool}: {result.content[0].text}"
            return result.structured_content
        yield run


async def test_the_api_says_that_it_requires_a_version(call, strict):
    status = await call("api_status")
    assert status["requireIfMatch"] is True
    refused = _without_version(strict)
    assert refused == 428, "the API of these tests refuses a change that says no version"


def _without_version(api) -> int:
    import urllib.error
    import urllib.request

    m = _admin(api, "POST", "/models", {"xmiIdentifier": f"id-{uuid.uuid4().hex}", "name": "No version"})
    try:
        request = urllib.request.Request(f"{api.url}/api/v2/models/{m['id']}", data=b'{"name": "x"}', method="PUT",
                                         headers={"X-API-Key": ADMIN_KEY, "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as e:
            return e.code
        return 200
    finally:
        _admin(api, "DELETE", f"/models/{m['id']}")


async def test_every_write_tool_sends_a_version(call, model, strict):
    m = model["id"]
    clerk = (await call("create_element", model=m, type="BusinessActor", name="Clerk"))["created"]
    desk = (await call("create_element", model=m, type="BusinessRole", name="Desk"))["created"]
    rel = (await call("create_relationship", model=m, type="Assignment", source=clerk["id"], target=desk["id"]))
    rel_id = rel["created"]["id"]
    await call("update_element", model=m, element="Clerk", name="Senior clerk")
    await call("update_relationship", model=m, relationship=rel_id, name="works at")
    await call("set_property", model=m, item="Senior clerk", name="Owner", value="Sales")
    await call("set_property", model=m, item="Senior clerk", name="Owner", value="Support")  # replaces it
    await call("remove_property", model=m, item="Senior clerk", name="Owner")

    # the model's own properties: the second call replaces the value (a PUT of it)
    await call("set_property", model=m, kind="model", name="Status", value="draft")
    again = await call("set_property", model=m, kind="model", name="Status", value="final")
    assert again["previous"] == "draft"
    await call("remove_property", model=m, kind="model", name="Status")

    # folders and filing
    await call("create_folder", model=m, name="Teams", parent="Business")
    await call("create_folder", model=m, name="Old", parent="Business")
    await call("update_folder", model=m, folder="Business/Teams", name="People")
    filed = await call("file_item", model=m, item="Senior clerk", folder="Business/People")
    assert filed["folder"] == "Business/People" and filed["previously"] == ["Business"]
    await call("file_item", model=m, item="Desk", folder="Business/Old")
    gone = await call("delete_folder", model=m, folder="Business/Old", move_contents_to="Business/People")
    assert gone["contentsMoved"]["to"] == "Business/People"
    found = await call("browse_folders", model=m, folder="Business/People")
    assert sorted(e["name"] for e in found["elements"]["items"]) == ["Desk", "Senior clerk"], found

    # many changes at once, by name and by id, one item twice (both against its version before the call)
    done = await call("apply_changes", model=m, changes=[
        {"op": "updateElement", "element": "Senior clerk", "documentation": "Handles orders"},
        {"op": "setProperty", "item": clerk["id"], "name": "Owner", "value": "Sales"},
        {"op": "updateRelationship", "relationship": rel_id, "documentation": "Full time"},
        {"op": "fileItem", "item": "Desk", "folder": "Business"},
        {"op": "updateFolder", "folder": "Business/People", "name": "Staff"},
        {"op": "createFolder", "ref": "tmp", "name": "Temporary", "parent": "Business"},
        {"op": "deleteFolder", "folder": "@tmp"},
    ])
    assert done["applied"] == 7
    await call("apply_changes", model=m, changes=[
        {"op": "deleteRelationship", "relationship": rel_id},
        {"op": "deleteElement", "element": "Desk"},
        {"op": "deleteFolder", "folder": "Business/Staff", "move_contents_to": "Business"},
    ])

    # a created view, and the model itself
    # (made as the Browser makes one: the MCP server only proposes views)
    view = _admin(strict, "POST", f"/models/{m}/views", {"name": "Mine", "content": {
        "nodes": [{"ref": "a", "elementId": clerk["id"], "x": 10, "y": 10, "w": 120, "h": 55}]}})
    await call("update_view", model=m, view=view["id"], name="Ours")
    await call("apply_changes", model=m, changes=[{"op": "updateView", "view": "Ours", "documentation": "x"}])
    await call("delete_view", model=m, view="Ours")
    await call("update_model", model=m, documentation="Checked against REQUIRE_IF_MATCH")
    await call("delete_element", model=m, element="Senior clerk")
