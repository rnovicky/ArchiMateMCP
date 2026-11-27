"""1.15.0 (API 3.24.0): recipe scripts (check_recipe_script, run_recipe_script) and neighbourhoods with relationship
types per direction, against the real API."""

from __future__ import annotations

import uuid

import pytest
from mcp import Client

from app.server import build_server

from .api_server import EDITOR_KEY, READER_KEY
from .conftest import make_settings
from .test_graph import BROWSER, hash_of
from .test_tools import SYNTHETIC
from .test_write import _admin

pytestmark = pytest.mark.anyio


@pytest.fixture
def model(api):
    """A model of its own: three components with an Owner, a service they serve, a node that serves ERP."""
    m = _admin(api, "POST", "/models", {"xmiIdentifier": f"id-{uuid.uuid4().hex}", "name": f"Scripts {uuid.uuid4().hex[:8]}"})
    ops = [{"op": "createElement", "ref": ref, "type": t, "name": name, "xmiIdentifier": ref,
            **({"properties": {"Owner": owner}} if owner else {})}
           for ref, t, name, owner in [("app-erp", "ApplicationComponent", "ERP", "Finance"),
                                       ("app-crm", "ApplicationComponent", "CRM", "Sales"),
                                       ("app-bill", "ApplicationComponent", "Billing", "Finance"),
                                       ("svc-order", "BusinessService", "Ordering", None),
                                       ("node-1", "Node", "Server", None)]]
    ops += [{"op": "createRelationship", "type": "Serving", "source": {"elementRef": "app-erp"},
             "target": {"elementRef": "svc-order"}},
            {"op": "createRelationship", "type": "Serving", "source": {"elementRef": "node-1"},
             "target": {"elementRef": "app-erp"}},
            {"op": "createRelationship", "type": "Flow", "source": {"elementRef": "app-erp"},
             "target": {"elementRef": "app-crm"}}]
    _admin(api, "POST", f"/models/{m['id']}/changes", {"operations": ops})
    return m


@pytest.fixture
async def call(api, tmp_path):
    settings = make_settings(api_url=api.url, api_key=EDITOR_KEY, allow_write=True, browser_url=BROWSER,
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
        run.log = tmp_path / "changes.log"
        yield run


SCRIPT = """script "Owners"
for each ApplicationComponent where @Owner = "finance"
  diagram "App: {name}"
    neighbourhood depth 1
      incoming all
      outgoing Serving
"""


async def test_check_lists_the_recipes_with_links(call, model):
    body = await call("check_recipe_script", model=model["name"], script=SCRIPT)
    assert body["ok"] is True and body["script"] == "Owners"
    assert body["counts"] == {"new": 2, "changed": 0, "unchanged": 0, "obsolete": 0}
    items = body["recipes"]["items"]
    assert [(r["name"], r["status"], r["for"]["name"]) for r in items] == [("App: Billing", "new", "Billing"),
                                                                            ("App: ERP", "new", "ERP")]
    erp = items[1]
    assert erp["recipe"] == "d=nb~1~app-erp~b~~Serving&n=0"
    assert hash_of(erp["browserLink"])["d"] == "nb~1~app-erp~b~~Serving"
    assert "ask before running it with run_recipe_script" in body["next"]


async def test_check_reports_errors_by_line(call, model):
    body = await call("check_recipe_script", model=model["name"],
                      script='script "x"\nfor each ApplicationComponnt\n  diagram "{name}"\n    neighbourhood\n')
    assert body["ok"] is False and "recipes" not in body
    assert body["errors"][0]["line"] == 2 and "did you mean ApplicationComponent" in body["errors"][0]["message"]
    assert "Fix the errors" in body["next"]


async def test_run_makes_then_updates_its_recipes(call, model):
    first = await call("run_recipe_script", model=model["name"], script=SCRIPT)
    assert first["changed"] is True and first["counts"]["new"] == 2 and first["revision"]
    ids = {r["name"]: r["viewId"] for r in first["recipes"]["items"]}
    assert all(ids.values())
    views = await call("list_views", model=model["name"])
    assert {"App: Billing", "App: ERP"} <= {v["name"] for v in views["views"]["items"]}
    assert "run_recipe_script" in call.log.read_text(encoding="utf-8")
    again = await call("run_recipe_script", model=model["name"], script=SCRIPT)
    assert again["changed"] is False and again["counts"]["unchanged"] == 2
    # CRM becomes Finance's, Billing is left out: one new, one obsolete
    narrower = SCRIPT.replace('= "finance"', '!= "Sales" and name != "Billing"')
    checked = await call("check_recipe_script", model=model["name"], script=narrower)
    assert checked["counts"] == {"new": 0, "changed": 0, "unchanged": 1, "obsolete": 1}
    assert checked["obsolete"][0]["name"] == "App: Billing"
    gone = await call("run_recipe_script", model=model["name"], script=narrower, delete_obsolete=True)
    assert gone["obsolete"][0]["deleted"] is True
    assert ids["App: Billing"] not in {v["id"] for v in (await call("list_views", model=model["name"]))["views"]["items"]}


async def test_run_with_errors_changes_nothing(call, model):
    body = await call("run_recipe_script", model=model["name"], script=SCRIPT + "    layout fancy\n")
    assert body["ok"] is False and body["changed"] is False
    assert body["errors"][0]["line"] == 7


async def test_only_check_without_writing(api, model):
    settings = make_settings(api_url=api.url, api_key=READER_KEY)
    async with Client(build_server(settings)) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert "check_recipe_script" in tools and "run_recipe_script" not in tools
        assert tools["check_recipe_script"].annotations.read_only_hint is True
        assert "for each BusinessService" in tools["check_recipe_script"].description
        result = await c.call_tool("check_recipe_script", {"model": model["name"], "script": SCRIPT})
        assert "Running it needs writing" in result.structured_content["next"]
    writing = make_settings(api_url=api.url, api_key=EDITOR_KEY, allow_write=True, change_log="")
    async with Client(build_server(writing, writable=True)) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert tools["run_recipe_script"].annotations.read_only_hint is False


async def test_neighbourhood_with_relationship_types_per_direction(call):
    plain = await call("neighbourhood", model=SYNTHETIC, elements=["ERP"])
    typed = await call("neighbourhood", model=SYNTHETIC, elements=["ERP"], outgoing_types=["Realization"])
    names = lambda body: {e["name"] for e in body["elements"]["items"]}  # noqa: E731
    assert names(typed) < names(plain)
    assert "Order API" in names(typed) and "ERP Billing" not in names(typed), "Composition is not followed outwards"
    assert hash_of(typed["browserLink"])["d"] == "nb~1~app-erp~b~~Realization"
    message = await call.fails("neighbourhood", model=SYNTHETIC, elements=["ERP"], direction="out",
                               incoming_types=["Serving"])
    assert "incoming_types needs direction both or in" in message
