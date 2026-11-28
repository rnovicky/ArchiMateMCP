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


# ================================================================ 1.16.0 (API 3.25.0): kept scripts, a recipe as a script

async def test_a_run_keeps_the_script(call, model):
    ran = await call("run_recipe_script", model=model["name"], script=SCRIPT)
    assert ran["storedScriptId"]
    listed = await call("recipe_scripts", model=model["name"])
    assert [(x["name"], x["recipes"], x["stored"]) for x in listed["scripts"]] == [("Owners", 2, True)]
    one = await call("recipe_scripts", model=model["name"], name="owners")
    assert one["text"] == SCRIPT
    assert "no recipe script" in await call.fails("recipe_scripts", model=model["name"], name="Nope")


async def test_a_recipe_as_a_script(call, model, api):
    view_id = _admin(api, "POST", f"/models/{model['id']}/views", {"name": "ERP around", "recipe": "d=nb~1~app-erp&n=0"})["id"]
    view = await call("get_view", model=model["name"], view=view_id)
    assert view["script"] == 'diagram "ERP around"\n  neighbourhood of "ERP" depth 1\n'
    assert "save_recipe_script" in view["note"]
    same = await call("check_recipe_script", model=model["name"], view=view_id, script=view["script"])
    assert same["ok"] and same["changes"] == [] and "nothing to save" in same["next"]
    wider = view["script"].replace("depth 1", "depth 2")
    checked = await call("check_recipe_script", model=model["name"], view=view_id, script=wider)
    assert checked["changes"] == ["recipe"] and "ask before saving" in checked["next"]
    saved = await call("save_recipe_script", model=model["name"], view=view_id, script=wider,
                       expected_version=view["version"])
    assert saved["changed"] is True and saved["recipe"]["recipe"] == "d=nb~2~app-erp&n=0"
    assert "save_recipe_script" in call.log.read_text(encoding="utf-8")
    bad = await call("save_recipe_script", model=model["name"], view=view_id, script='diagram "x"\n  neighbourhod\n')
    assert bad["ok"] is False and bad["errors"][0]["line"] == 2


async def test_a_recipe_made_by_a_script_points_to_it(call, model):
    ran = await call("run_recipe_script", model=model["name"], script=SCRIPT)
    view_id = ran["recipes"]["items"][0]["viewId"]
    view = await call("get_view", model=model["name"], view=view_id)
    assert view["madeBy"]["script"] == "Owners" and view["madeBy"]["line"] == 3
    checked = await call("check_recipe_script", model=model["name"], view=view_id, script=view["script"])
    assert "change that script instead" in checked["next"]
    refused = await call.fails("save_recipe_script", model=model["name"], view=view_id,
                               script=view["script"].replace("depth 1", "depth 2"))
    assert "detach=true" in refused
    detached = await call("save_recipe_script", model=model["name"], view=view_id,
                          script=view["script"].replace("depth 1", "depth 2"), detach=True)
    assert detached["detached"] is True


# ================================================================ 1.17.0 (API 3.26.0): live templates

async def test_keep_a_live_template(call, model):
    live = SCRIPT.replace('"Owners"', '"Live owners"')
    kept = await call("keep_recipe_script", model=model["name"], script=live)
    assert kept["ok"] and kept["live"] is True and kept["diagrams"] == 2 and "model tree" in kept["next"]
    assert "keep_recipe_script" in call.log.read_text(encoding="utf-8")
    listed = await call("recipe_scripts", model=model["name"])
    assert [(x["name"], x["live"], x["recipes"]) for x in listed["scripts"]] == [("Live owners", True, 0)]
    one = await call("recipe_scripts", model=model["name"], name="Live owners")
    assert one["live"] is True and [d["name"] for d in one["diagrams"]] == ["App: Billing", "App: ERP"]
    assert one["diagrams"][1]["browserLink"].startswith(BROWSER)
    bad = await call("keep_recipe_script", model=model["name"], script='script "x"\ndiagram "D"\n  neighbourhod\n')
    assert bad["ok"] is False and bad["errors"][0]["line"] == 3
    await call("run_recipe_script", model=model["name"], script=SCRIPT)
    clash = await call.fails("keep_recipe_script", model=model["name"], script=SCRIPT)
    assert "made 2 recipe" in clash
