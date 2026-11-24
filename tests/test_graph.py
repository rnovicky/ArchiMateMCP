"""
Phase 2 (MCP-8 to MCP-13): the graph tools, links to the ArchiMate Browser,
resources and prompts, against the real API with the synthetic model.
"""

from __future__ import annotations

import json
from urllib.parse import unquote

import pytest
from mcp import Client

from app.links import BrowserLinks, escape_ref, folder_token
from app.server import build_server

from .api_server import READER_KEY
from .conftest import make_settings
from .test_tools import SYNTHETIC, by_name

pytestmark = pytest.mark.anyio

BROWSER = "http://127.0.0.1:8090/"


@pytest.fixture
async def client(api):
    """An MCP client of a server that knows the browser's address."""
    settings = make_settings(api_url=api.url, api_key=READER_KEY, browser_url=BROWSER)
    async with Client(build_server(settings)) as c:
        yield c


async def call(client, tool, **arguments):
    result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def error(client, tool, **arguments):
    result = await client.call_tool(tool, arguments)
    assert result.is_error, result.structured_content
    return result.content[0].text


def hash_of(link: str) -> dict[str, str]:
    assert link.startswith(BROWSER + "#"), link
    return dict(part.split("=", 1) for part in unquote(link[len(BROWSER) + 1:]).split("&"))


# ---------------------------------------------------------------- MCP-8

async def test_impact_analysis(client):
    a = await call(client, "impact_analysis", model=SYNTHETIC, elements=["Kafka"])
    assert a["direction"] == "impact" and [e["name"] for e in a["start"]] == ["Kafka"]
    level1 = by_name(a["levels"][0]["elements"])
    assert a["levels"][0]["level"] == 1 and "ERP" in level1
    assert level1["ERP"]["via"]["type"] == "Flow" and level1["ERP"]["from"] == a["start"][0]["id"]
    level2 = by_name(a["levels"][1]["elements"])
    assert level2["Order API"]["via"]["type"] == "Realization" and level2["Order API"]["from"] == level1["ERP"]["id"]
    assert a["reached"] == sum(len(level["elements"]) for level in a["levels"])
    assert hash_of(a["browserLink"]) == {"model": "synthetic-model", "d": "im~app-kafka~i~3"}


async def test_dependencies_with_types_and_limit(client):
    a = await call(client, "impact_analysis", model=SYNTHETIC, elements=["Order API", "app-kafka"],
                   direction="dependencies", max_depth=2, relationship_types=["Realization", "Flow"], limit=1)
    assert a["direction"] == "dependencies" and len(a["start"]) == 2
    assert sum(len(level["elements"]) for level in a["levels"]) == 1 and a["truncated"] and a["reached"] > 1
    assert hash_of(a["browserLink"])["d"] == "im~svc-order-api.app-kafka~d~2~Realization.Flow"


# ---------------------------------------------------------------- MCP-9

async def test_find_paths(client):
    p = await call(client, "find_paths", model=SYNTHETIC, source="Web Shop", target="ERP")
    texts = [path["text"] for path in p["paths"]]
    assert "Web Shop -Flow-> Kafka -Flow-> ERP" in texts
    assert "Web Shop <-Serving- Order API <-Realization- ERP" in texts
    assert all(path["length"] == 2 for path in p["paths"][:2])
    step = p["paths"][0]["steps"][1]
    assert set(step) == {"relationshipId", "type", "direction"}
    assert hash_of(p["browserLink"])["d"] == "pa~app-shop~app-erp"


async def test_find_paths_directed_and_none(client):
    p = await call(client, "find_paths", model=SYNTHETIC, source="Web Shop", target="ERP", directed=True)
    assert [path["text"] for path in p["paths"]] == ["Web Shop -Flow-> Kafka -Flow-> ERP"]
    none = await call(client, "find_paths", model=SYNTHETIC, source="Unused Component", target="ERP")
    assert none["paths"] == []
    assert "same element" in await error(client, "find_paths", model=SYNTHETIC, source="ERP", target="app-erp")


# ---------------------------------------------------------------- MCP-10

async def test_neighbourhood(client):
    n = await call(client, "neighbourhood", model=SYNTHETIC, elements=["Kafka"])
    elements = by_name(n["elements"]["items"])
    assert elements["Kafka"]["distance"] == 0
    assert {"Web Shop", "ERP", "Kafka Connect", "Core Systems"} <= set(elements)
    assert all(e["distance"] <= 1 for e in elements.values())
    flows = {(r["source"]["name"], r["target"]["name"]) for r in n["relationships"]["items"] if r["type"] == "Flow"}
    assert flows == {("Web Shop", "Kafka"), ("Kafka", "ERP")}
    assert hash_of(n["browserLink"])["d"] == "nb~1~app-kafka"
    out = await call(client, "neighbourhood", model=SYNTHETIC, elements=["Kafka"], direction="out", depth=2)
    assert hash_of(out["browserLink"])["d"] == "nb~2~app-kafka~o"
    deep = await call(client, "neighbourhood", model=SYNTHETIC, elements=["Kafka"], depth=4)
    assert hash_of(deep["browserLink"]) == {"model": "synthetic-model"}  # the browser draws 3 at most


async def test_subgraph(client):
    s = await call(client, "subgraph", model=SYNTHETIC, elements=["ERP", "ERP Billing", "Kafka"])
    assert set(by_name(s["elements"]["items"])) == {"ERP", "ERP Billing", "Kafka"}
    pairs = {(r["type"], r["source"]["name"], r["target"]["name"]) for r in s["relationships"]["items"]}
    assert ("Composition", "ERP", "ERP Billing") in pairs and ("Flow", "Kafka", "ERP") in pairs
    assert hash_of(s["browserLink"])["d"] == "el~app-erp.app-erp-billing.app-kafka"
    folder = await call(client, "subgraph", model=SYNTHETIC, folder="Application/ERP domain")
    assert set(by_name(folder["elements"]["items"])) == {"ERP", "ERP Billing", "ERP Stock"}
    assert hash_of(folder["browserLink"])["d"] == "fo~@Application:ERP*20domain"
    layer = await call(client, "subgraph", model=SYNTHETIC, layer="Technology")
    assert layer["elements"]["total"] == 3 and hash_of(layer["browserLink"])["d"] == "la~technology"
    view = await call(client, "subgraph", model=SYNTHETIC, view="Overview")
    assert hash_of(view["browserLink"])["d"] == "v~v-overview"
    assert "exactly one" in await error(client, "subgraph", model=SYNTHETIC, layer="Business", view="Overview")


# ---------------------------------------------------------------- MCP-11

async def test_browser_link(client):
    link = (await call(client, "browser_link", model=SYNTHETIC, elements=["ERP", "Kafka"], select="ERP"))["browserLink"]
    assert hash_of(link) == {"model": "synthetic-model", "element": "app-erp", "d": "el~app-erp.app-kafka"}
    folder = (await call(client, "browser_link", model=SYNTHETIC, folder="Process"))["browserLink"]
    assert hash_of(folder)["d"] == "fo~@Views:Details:Process"


async def test_links_in_other_answers(client):
    element = await call(client, "get_element", model=SYNTHETIC, element="ERP")
    assert hash_of(element["browserLink"]) == {"model": "synthetic-model", "element": "app-erp"}
    view = await call(client, "get_view", model=SYNTHETIC, view="Overview")
    assert hash_of(view["browserLink"])["d"] == "v~v-overview"
    folder = await call(client, "browse_folders", model=SYNTHETIC, folder="Application")
    assert hash_of(folder["browserLink"])["d"] == "fo~@Application"


async def test_no_links_without_browser_url(settings):
    async with Client(build_server(settings)) as c:
        element = await call(c, "get_element", model=SYNTHETIC, element="ERP")
        assert "browserLink" not in element
        assert "BROWSER_URL" in await error(c, "browser_link", model=SYNTHETIC, view="Overview")
        assert "BROWSER_URL" in await error(c, "propose_view", model=SYNTHETIC, name="X", elements=["ERP"])


# ---------------------------------------------------------------- MCP-28 (1.9.0)

async def test_propose_view_is_a_link_that_stores_nothing(client):
    before = (await call(client, "list_views", model=SYNTHETIC))["views"]["total"]
    a = await call(client, "propose_view", model=SYNTHETIC, name="Order integration",
                   elements=["app-kafka", "app-erp", "svc-order-api"])
    assert a["stored"] is False and a["name"] == "Order integration"
    assert sorted(r["type"] for r in a["relationships"]["items"]) == ["Flow", "Realization"]
    h = hash_of(a["browserLink"])
    assert h["vn"] == "Order integration"
    assert h["d"] == "ex~~app-kafka.app-erp.svc-order-api", "every relationship between them: none hidden"
    # only some relationships: the others between them are hidden; one of other elements is left out, said so
    b = await call(client, "propose_view", model=SYNTHETIC, name="Realization only",
                   elements=["app-kafka", "app-erp", "svc-order-api"], relationships=["r-real-erp-api", "r-flow-shop-kafka"])
    assert [r["type"] for r in b["relationships"]["items"]] == ["Realization"]
    assert hash_of(b["browserLink"])["d"] == "ex~~app-kafka.app-erp.svc-order-api~r-flow-kafka-erp"
    assert "does not join two of the elements" in b["warnings"][0]
    assert (await call(client, "list_views", model=SYNTHETIC))["views"]["total"] == before, "nothing stored"


async def test_the_views_of_a_source_say_so(client):
    views = (await call(client, "list_views", model=SYNTHETIC))["views"]["items"]
    assert views and {v["origin"] for v in views} == {"source"}
    assert (await call(client, "list_views", model=SYNTHETIC, origin="created"))["views"]["total"] == 0
    assert (await call(client, "get_view", model=SYNTHETIC, view="Overview"))["origin"] == "source"


def test_link_tokens():
    assert escape_ref("id-3f2a") == "id-3f2a"
    assert escape_ref("a b/č") == "a*20b*2F*C4*8D"
    tree = [{"id": 1, "label": "A", "children": [{"id": 2, "label": "B C", "children": []},
                                                {"id": 3, "label": "B C", "children": []}]},
            {"id": 4, "label": "X", "xmiIdentifier": "f-x", "children": []}]
    assert folder_token(tree, 2) == "@A:B*20C"
    assert folder_token(tree, 3) == "3"  # its path would name folder 2, the first with that label
    assert folder_token(tree, 4) == "f-x"
    assert BrowserLinks("http://h/app").url("m", "el~1") == "http://h/app/#model=m&d=el~1"
    assert BrowserLinks("").url("m") is None


# ---------------------------------------------------------------- MCP-12

async def test_resources(client, api):
    listed = {str(r.uri) for r in (await client.list_resources()).resources}
    assert {"archimate://metamodel", "archimate://models"} <= listed
    templates = {t.uri_template for t in (await client.list_resource_templates()).resource_templates}
    assert {"archimate://models/{model}/views/{view}", "archimate://models/{model}/elements/{element}"} <= templates

    async def read(uri):
        return json.loads((await client.read_resource(uri)).contents[0].text)

    metamodel = await read("archimate://metamodel")
    assert "ApplicationComponent" in by_key(metamodel["layers"])["Application"]["elementTypes"]
    assert metamodel["impact"]["propagation"]["Serving"] == "out"
    assert {m["name"] for m in await read("archimate://models")} == {SYNTHETIC, "Basic Model"}
    model = api.models["synthetic"]
    overview = await call(client, "get_view", model=str(model), view="Overview")
    view = await read(f"archimate://models/{model}/views/{overview['id']}")
    assert view["name"] == "Overview" and view["elements"] == overview["elements"]
    erp = await call(client, "get_element", model=str(model), element="ERP")
    assert (await read(f"archimate://models/{model}/elements/{erp['id']}"))["name"] == "ERP"


def by_key(items):
    return {i["key"]: i for i in items}


# ---------------------------------------------------------------- MCP-13

async def test_prompts(client):
    prompts = {p.name: p for p in (await client.list_prompts()).prompts}
    assert set(prompts) >= {"impact_of_change", "describe_view", "model_quality_review"}
    assert [a.name for a in prompts["impact_of_change"].arguments if a.required] == ["element"]
    text = (await client.get_prompt("impact_of_change", {"element": "ERP", "model": SYNTHETIC})).messages[0].content.text
    assert '"ERP"' in text and SYNTHETIC in text and "impact_analysis" in text and "browserLink" in text
    review = (await client.get_prompt("model_quality_review", {})).messages[0].content.text
    assert "model_overview" in review
