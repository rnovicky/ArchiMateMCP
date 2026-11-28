"""
Phase 1, the reading tools (MCP-1 to MCP-7), against the real API with the
synthetic model (tests/fixtures/build_synthetic_model.py of the API) and
the basic model.
"""

from __future__ import annotations

import json

import pytest
from mcp import Client

from app.server import build_server

from .api_server import READER_KEY
from .conftest import make_settings

pytestmark = pytest.mark.anyio

SYNTHETIC = "Synthetic Test Model"


@pytest.fixture
async def call(settings):
    """call(tool, **arguments) -> the structured answer; a tool error fails the test."""
    async with Client(build_server(settings)) as client:
        async def run(tool: str, **arguments):
            result = await client.call_tool(tool, arguments)
            assert not result.is_error, result.content[0].text
            return result.structured_content
        run.client = client
        yield run


@pytest.fixture
async def error(settings):
    """error(tool, **arguments) -> the message of the tool error it must give."""
    async with Client(build_server(settings)) as client:
        async def run(tool: str, **arguments):
            result = await client.call_tool(tool, arguments)
            assert result.is_error, result.structured_content
            return result.content[0].text
        yield run


def by_name(items):
    return {i["name"]: i for i in items}


# ---------------------------------------------------------------- tools

async def test_the_tools_and_their_hints(call):
    tools = {t.name: t for t in (await call.client.list_tools()).tools}
    assert {"api_status", "list_models", "model_overview", "search", "get_element", "get_relationship",
            "list_views", "get_view", "browse_folders"} <= set(tools)
    assert all(not t.annotations.destructive_hint for t in tools.values())
    assert all(t.annotations.read_only_hint for n, t in tools.items() if n not in ("diagram_image", "recipe_images"))  # it writes image files
    assert all(t.description for t in tools.values())


async def test_answers_are_compact_json(call):
    result = await call.client.call_tool("search", {"model": SYNTHETIC, "query": "účtování"})
    text = result.content[0].text
    assert json.loads(text) == result.structured_content
    assert "\n" not in text and "Účtování objednávky" in text  # not indented, not escaped
    tools = {t.name: t for t in (await call.client.list_tools()).tools}
    assert tools["search"].output_schema["type"] == "object"


# ---------------------------------------------------------------- MCP-1, MCP-2

async def test_list_models(call, api):
    answer = await call("list_models")
    models = by_name(answer["models"])
    assert answer["total"] == 2 and set(models) == {SYNTHETIC, "Basic Model"}
    synthetic = models[SYNTHETIC]
    assert (synthetic["id"], synthetic["elements"], synthetic["relationships"], synthetic["views"]) == (
        api.models["synthetic"], 30, 31, 4)
    assert "linkedTo" not in synthetic


async def test_a_model_must_be_named_when_there_are_several(error):
    message = await error("model_overview")
    assert "Say which model" in message and SYNTHETIC in message and "Basic Model" in message


async def test_a_model_by_id_name_or_part_of_it(call, api):
    for ref in (str(api.models["synthetic"]), SYNTHETIC, "synthetic test model", "Synthetic"):
        assert (await call("model_overview", model=ref))["model"]["id"] == api.models["synthetic"], ref


async def test_unknown_model(error):
    assert "No model is called" in await error("model_overview", model="Nonexistent")


async def test_default_model(api):
    settings = make_settings(api_url=api.url, api_key=READER_KEY, default_model=SYNTHETIC)
    async with Client(build_server(settings)) as client:
        result = await client.call_tool("model_overview", {})
    assert not result.is_error and result.structured_content["model"]["name"] == SYNTHETIC


async def test_model_overview(call):
    o = await call("model_overview", model=SYNTHETIC)
    assert o["elements"]["total"] == 30 and o["elements"]["byLayer"]["Application"] == 11
    assert o["elements"]["byType"]["ApplicationComponent"] == 9
    assert o["relationships"]["byType"]["Realization"] == 5
    assert o["views"] == 4
    folders = by_name(o["folders"])
    assert folders["Application"]["elements"] == 10 and folders["Views"]["views"] == 3
    properties = by_name(o["properties"])
    assert properties["Owner"]["count"] == 7 and properties["Owner"]["topValues"]["Finance"] == 3
    assert properties["Cost"]["dataType"] == "number"


# ---------------------------------------------------------------- MCP-3

async def test_search_ranks_and_groups(call):
    s = await call("search", model=SYNTHETIC, query="order")
    names = [e["name"] for e in s["elements"]["items"]]
    assert names[0] == "Order"  # equal to the text: first
    assert {"Order API", "Create Order", "Ship Order"} <= set(names)
    assert by_name(s["elements"]["items"])["Order"]["matchedIn"] == ["name"]
    assert by_name(s["views"]["items"])["Order Process"]["viewpoint"] == "Business Process Cooperation"


async def test_search_relationships_name_their_ends(call):
    s = await call("search", model=SYNTHETIC, query="order events", kinds=["relationships"])
    assert set(s) == {"model", "relationships"}
    flows = {(r["source"]["name"], r["target"]["name"]) for r in s["relationships"]["items"]}
    assert flows == {("Web Shop", "Kafka"), ("Kafka", "ERP")}


async def test_search_by_filters(call):
    s = await call("search", model=SYNTHETIC, kinds=["elements"], layers=["Technology"])
    assert {e["name"] for e in s["elements"]["items"]} == {"App Server", "Database", "erp.jar"}
    s = await call("search", model=SYNTHETIC, kinds=["elements"], element_types=["ApplicationComponent"],
                   property="Owner", property_value="finance")
    assert "ERP" in {e["name"] for e in s["elements"]["items"]}
    s = await call("search", model=SYNTHETIC, query="system of record", fields=["documentation"], kinds=["elements"])
    assert [e["name"] for e in s["elements"]["items"]] == ["ERP"]


async def test_search_is_cut_at_the_limit(call):
    s = await call("search", model=SYNTHETIC, kinds=["elements"], layers=["Application"], limit=3)
    assert len(s["elements"]["items"]) == 3 and s["elements"]["total"] == 11 and s["elements"]["truncated"]


async def test_search_refuses_an_unknown_type(error):
    message = await error("search", model=SYNTHETIC, element_types=["Nonsense"])
    assert message.startswith("Error executing tool search: 422: ") and "Nonsense" in message and "{" not in message


# ---------------------------------------------------------------- MCP-4, MCP-5

async def test_get_element(call):
    e = await call("get_element", model=SYNTHETIC, element="ERP")
    assert (e["type"], e["documentation"]) == ("ApplicationComponent", "System of record for orders and invoices.")
    assert e["properties"] == {"Owner": "Finance", "Cost": "1200", "Go-live": "2021-03-01"}
    assert e["folders"] == ["Application/ERP domain"]
    out = {(x["type"], x["element"]["name"]) for x in e["outgoing"]["items"] if "element" in x}
    assert {("Composition", "ERP Billing"), ("Aggregation", "ERP Stock"), ("Realization", "Order API")} <= out
    incoming = {(x["type"], x["element"]["name"]) for x in e["incoming"]["items"]}
    assert ("Flow", "Kafka") in incoming
    assert "Overview" in {v["name"] for v in e["views"]["items"]}


async def test_get_element_by_id_and_xmi_identifier(call):
    by_xmi = await call("get_element", model=SYNTHETIC, element="app-erp")
    by_id = await call("get_element", model=SYNTHETIC, element=str(by_xmi["id"]))
    assert by_xmi["name"] == by_id["name"] == "ERP"


async def test_an_exact_name_wins(call):
    # "erp" is part of ERP Billing, ERP Stock, erp.jar, Migrate ERP too, but one name is exactly it
    assert (await call("get_element", model=SYNTHETIC, element="erp "))["name"] == "ERP"


async def test_get_element_with_a_name_part(call, error):
    # "Billing" is part of one name only
    assert (await call("get_element", model=SYNTHETIC, element="billing"))["name"] == "ERP Billing"
    message = await error("get_element", model=SYNTHETIC, element="Kafk")
    assert "matches 2 elements" in message and "Kafka (ApplicationComponent, id" in message
    assert "Ask again with the id" in message


async def test_get_element_non_ascii_name(call):
    e = await call("get_element", model=SYNTHETIC, element="účtování objednávky")
    assert e["type"] == "BusinessProcess"


async def test_get_relationship(call):
    e = await call("get_element", model=SYNTHETIC, element="Web Shop")
    flow = next(x for x in e["outgoing"]["items"] if x["type"] == "Flow")
    r = await call("get_relationship", model=SYNTHETIC, relationship=str(flow["relationshipId"]))
    assert (r["name"], r["source"]["name"], r["target"]["name"]) == ("order events", "Web Shop", "Kafka")
    assert r["properties"] == {"Owner": "Integration"}
    assert {v["name"] for v in r["views"]["items"]} >= {"Overview"}
    assert (await call("get_relationship", model=SYNTHETIC, relationship="r-flow-shop-kafka"))["id"] == r["id"]


async def test_relationship_on_a_relationship(call):
    r = await call("get_relationship", model=SYNTHETIC, relationship="r-assoc-req-flow")
    assert r["source"]["name"] == "Traceable orders"
    assert r["target"]["isRelationship"] and r["target"]["type"] == "Flow"


async def test_unknown_relationship(error):
    assert "No relationship has the id or XMI identifier" in await error("get_relationship", model=SYNTHETIC,
                                                                         relationship="order events")


# ---------------------------------------------------------------- MCP-6

async def test_list_views(call):
    views = (await call("list_views", model=SYNTHETIC))["views"]
    assert views["total"] == 4 and "Empty View" in by_name(views["items"])
    assert [v["name"] for v in (await call("list_views", model=SYNTHETIC, name="order"))["views"]["items"]] == [
        "Order Process"]
    shown = (await call("list_views", model=SYNTHETIC, element="ERP"))["views"]["items"]
    assert "Overview" in by_name(shown)


async def test_get_view(call):
    v = await call("get_view", model=SYNTHETIC, view="Overview")
    assert v["viewpoint"] == "Layered" and v["properties"] == {"Owner": "Architecture team"}
    elements = by_name(v["elements"]["items"])
    assert {"Web Shop", "Kafka", "ERP", "ERP Billing", "ERP Stock"} <= set(elements)
    assert elements["ERP Billing"]["nestedIn"] == [elements["ERP"]["id"]]
    assert "nestedIn" not in elements["ERP"]
    flows = {(r["source"]["name"], r["target"]["name"]) for r in v["relationships"]["items"] if r["type"] == "Flow"}
    assert ("Web Shop", "Kafka") in flows
    assert by_name(v["groups"])["Integration zone"]["elements"] == [elements["Kafka Connect"]["id"]]
    assert {link["name"] for link in v["linksTo"]} == {"Order Process", "Technology"}
    assert [link["name"] for link in v["linkedFrom"]] == ["Order Process"]
    assert all(set(e) <= {"id", "name", "type", "nestedIn"} for e in v["elements"]["items"])  # no coordinates


async def test_an_empty_view(call):
    v = await call("get_view", model=SYNTHETIC, view="Empty View")
    assert v["elements"] == {"total": 0, "items": []} and v["relationships"]["total"] == 0


# ---------------------------------------------------------------- MCP-7

async def test_browse_folders_top_level(call):
    folders = by_name((await call("browse_folders", model=SYNTHETIC))["folders"])
    assert {"Strategy and Motivation", "Business", "Application", "Technology", "Views", "Archive"} <= set(folders)
    assert folders["Views"]["folders"] == 3 and folders["Archive"]["elements"] == 0


async def test_browse_a_folder_by_path(call):
    f = await call("browse_folders", model=SYNTHETIC, folder="Application")
    assert f["folder"]["path"] == "Application"
    assert [x["name"] for x in f["folders"]] == ["ERP domain"]
    assert f["elements"]["total"] == 7  # filed directly in it, not in ERP domain
    erp = await call("browse_folders", model=SYNTHETIC, folder="application/erp domain")
    assert erp["folder"]["path"] == "Application/ERP domain"
    assert {e["name"] for e in erp["elements"]["items"]} == {"ERP", "ERP Billing", "ERP Stock"}


async def test_browse_a_folder_by_name_or_id(call, error):
    process = await call("browse_folders", model=SYNTHETIC, folder="Process")
    assert process["folder"]["path"] == "Views/Details/Process"
    assert [v["name"] for v in process["views"]["items"]] == ["Order Process"]
    again = await call("browse_folders", model=SYNTHETIC, folder=str(process["folder"]["id"]))
    assert again["folder"]["path"] == "Views/Details/Process"
    assert "No folder is at or called" in await error("browse_folders", model=SYNTHETIC, folder="Nowhere")


# ---------------------------------------------------------------- phase 5: ids as numbers

async def test_ids_may_be_numbers(call, api):
    """Clients send an id as a number as often as as a string (Claude Code does)."""
    model = api.models["synthetic"]
    assert (await call("model_overview", model=model))["model"]["id"] == model
    erp = await call("get_element", model=model, element="ERP")
    assert (await call("get_element", model=model, element=erp["id"]))["name"] == "ERP"
    impact = await call("impact_analysis", model=model, elements=[erp["id"], "Kafka"])
    assert len(impact["start"]) == 2
    view = await call("get_view", model=model, view="Overview")
    assert (await call("get_view", model=model, view=view["id"]))["name"] == "Overview"


async def test_no_empty_match_fields(call):
    s = await call("search", model=SYNTHETIC, kinds=["elements"], layers=["Technology"])
    assert all("matchedIn" not in e for e in s["elements"]["items"])
