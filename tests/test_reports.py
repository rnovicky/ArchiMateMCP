"""MCP-18 to MCP-21: the reports of API 3.6.0 and the allowed relationships of 3.7.0, against the real API with the synthetic model."""

from __future__ import annotations

import pytest
from mcp import Client

from app.server import build_server

from .api_server import READER_KEY
from .conftest import make_settings
from .test_tools import SYNTHETIC

pytestmark = pytest.mark.anyio


@pytest.fixture
async def call(api):
    settings = make_settings(api_url=api.url, api_key=READER_KEY, browser_url="http://127.0.0.1:8090/")
    async with Client(build_server(settings)) as client:
        async def run(tool: str, **arguments):
            result = await client.call_tool(tool, arguments)
            assert not result.is_error, result.content[0].text
            return result.structured_content
        run.client = client
        yield run


async def test_model_quality(call):
    q = await call("model_quality", model=SYNTHETIC)
    assert set(q["summary"]) == {"elementsInNoView", "elementsWithoutRelationships", "unfiledElements",
                                 "unfiledRelationships", "unfiledViews", "duplicateNames", "emptyViews", "emptyLabels",
                                 "relationshipsNotAllowed"}
    # the synthetic model's Influence from a goal onto an Association
    [wrong] = q["checks"]["relationshipsNotAllowed"]["items"]
    assert (wrong["type"], wrong["sourceType"], wrong["targetType"]) == ("Influence", "Goal", "Relationship")
    assert wrong["source"] and wrong["target"]
    without = {e["name"] for e in q["checks"]["elementsWithoutRelationships"]["items"]}
    assert without == {"Unused Component", "Discount 50% Engine"}
    assert [v["name"] for v in q["checks"]["emptyViews"]["items"]] == ["Empty View"]
    some = await call("model_quality", model=SYNTHETIC, checks=["unfiledRelationships"], limit=3)
    assert list(some["checks"]) == ["unfiledRelationships"]
    group = some["checks"]["unfiledRelationships"]
    assert len(group["items"]) == 3 and group["truncated"] and group["total"] > 3


async def test_relationship_matrix_direct(call):
    m = await call("relationship_matrix", model=SYNTHETIC, rows={"element_type": "ApplicationComponent"},
                   columns={"element_type": "BusinessProcess"}, relationship_types=["Serving"], direction="out")
    assert m["cells"]["items"] == [{"row": "Web Shop", "column": "Create Order", "rowId": m["cells"]["items"][0]["rowId"],
                                    "columnId": m["cells"]["items"][0]["columnId"], "count": 1,
                                    "paths": ["Web Shop -Serving-> Create Order"]}]
    assert m["browserLink"].startswith("http://127.0.0.1:8090/#model=")


async def test_relationship_matrix_path_by_names(call):
    m = await call("relationship_matrix", model=SYNTHETIC, rows={"elements": ["ERP"]},
                   columns={"element_type": "ApplicationComponent"},
                   path=[{"types": ["Realization"], "direction": "out"}, {"types": ["Serving"], "direction": "out"}],
                   intermediate_types=[["ApplicationService"]])
    cell = m["cells"]["items"][0]
    assert (cell["row"], cell["column"]) == ("ERP", "Web Shop")
    assert cell["paths"] == ["ERP -Realization-> Order API -Serving-> Web Shop"]


async def test_relationship_matrix_through_junctions(call):
    m = await call("relationship_matrix", model=SYNTHETIC, rows={"elements": ["Create Order"]},
                   columns={"element_type": "BusinessProcess"}, relationship_types=["Triggering"], direction="out")
    paths = {c["column"]: c["paths"][0] for c in m["cells"]["items"]}
    assert paths["Ship Order"] == "Create Order -Triggering-> (junction) -Triggering-> (junction) -Triggering-> Ship Order"


async def test_a_set_needs_one_selector(call):
    result = await call.client.call_tool("relationship_matrix", {
        "model": SYNTHETIC, "rows": {"element_type": "Node", "layer": "Business"}, "columns": {"layer": "Business"}})
    assert result.is_error and "exactly one of" in result.content[0].text


async def test_landscape(call):
    tree = await call("landscape", model=SYNTHETIC, roots={"element_type": "Grouping"})
    core = tree["roots"][0]
    assert core["name"] == "Core Systems"
    erp = next(c for c in core["children"] if c["name"] == "ERP")
    assert [c["name"] for c in erp["children"]] == ["ERP Billing", "ERP Stock"] and erp["via"] == "Aggregation"
    assert tree["elements"] == 5
    caps = await call("landscape", model=SYNTHETIC, roots={"element_type": "Capability"},
                      nesting=[{"type": "Realization", "direction": "in"}], properties=["Owner"])
    order = caps["roots"][0]["children"][0]
    assert (order["name"], order["properties"]) == ("Create Order", {"Owner": "Sales"})
    assert caps["propertyValues"] == {"Owner": ["Sales"]}
    small = await call("landscape", model=SYNTHETIC, roots={"element_type": "Grouping"}, limit=2)
    assert small["elements"] == 2 and small["truncated"]


async def test_allowed_relationships(call):
    pair = await call("allowed_relationships", source_type="ApplicationComponent", target_type="DataObject")
    assert pair["allowed"] == ["Access", "Association"]
    targets = (await call("allowed_relationships", source_type="Grouping"))["targets"]
    assert targets["Relationship"] == ["Composition", "Aggregation", "Association"]
    sources = (await call("allowed_relationships", target_type="Goal"))["sources"]
    assert "Influence" in sources["Requirement"]
    for arguments in ({}, {"source_type": "Nonsense"}):
        result = await call.client.call_tool("allowed_relationships", arguments)
        assert result.is_error
    assert "source_type" in (await call.client.call_tool("allowed_relationships", {})).content[0].text
