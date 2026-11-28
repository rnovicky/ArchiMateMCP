"""
MCP-35 (1.12.0): diagram_image, drawn by the ArchiMate Browser (../ArchiMateBrowser, 2.29.0 or later) in Chrome or
Edge without a window, against the real API with the synthetic model. Skipped when Playwright or a browser is
missing; the checks of file names and links run without them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from app.render import browser_dir, browser_version
from app.server import build_server
from app.tools import images
from app.tools.images import link_hash, safe_name, target

from .api_server import READER_KEY
from .conftest import make_settings
from .test_tools import SYNTHETIC

BROWSER = "http://127.0.0.1:8090/"
PNG = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------- without a browser

def test_file_names(tmp_path):
    settings = make_settings(image_dir=str(tmp_path))
    assert target(settings, None, "View: Overview") == tmp_path / "View_Overview"
    assert target(settings, "report/overview.png", "x") == tmp_path / "report" / "overview"
    assert safe_name("Přehled – ERP") == "Přehled_ERP"
    assert safe_name("") == "diagram"
    for bad in ("../outside", str(tmp_path.parent / "elsewhere"), "."):
        with pytest.raises(ToolError, match="inside the image folder"):
            target(settings, bad, "x")


def test_image_dir_relative_to_the_server():
    from app.config import ROOT
    assert make_settings().image_path == (ROOT / "images").resolve()
    assert make_settings(image_dir="out/img").image_path == (ROOT / "out" / "img").resolve()


def test_links():
    assert link_hash("http://h:8090/#model=m&d=v~x") == "model=m&d=v~x"
    assert link_hash("#model=m&view=1") == "model=m&view=1"
    for bad in ("http://h:8090/", "#model=m", "d=v~x"):
        with pytest.raises(ToolError, match="link must be"):
            link_hash(bad)


def test_browser_folder(tmp_path):
    found = browser_dir(make_settings())
    assert found is None or (found / "server" / "serve.py").is_file()
    assert browser_dir(make_settings(browser_dir=str(tmp_path))) == tmp_path
    assert browser_version(tmp_path) is None
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "version.js").write_text("export const APP_VERSION = '2.29.1';\n", encoding="utf-8")
    assert browser_version(tmp_path) == (2, 29, 1)


# ---------------------------------------------------------------- drawn


@pytest.fixture(scope="module")
def drawable():
    """Skip when the images cannot be drawn here: no Playwright, no Browser 2.29.0 next to this project."""
    pytest.importorskip("playwright", reason="images need the Python package playwright")
    folder = browser_dir(make_settings())
    if folder is None or (browser_version(folder) or (0,)) < (2, 29, 0):
        pytest.skip("images need the ArchiMate Browser 2.29.0 or later next to this project")
    yield folder
    if images._renderer is not None:
        images._renderer.close()
        images._renderer = None


@pytest.fixture
async def client(api, drawable, tmp_path):
    settings = make_settings(api_url=api.url, api_key=READER_KEY, browser_url=BROWSER, image_dir=str(tmp_path))
    async with Client(build_server(settings)) as c:
        yield c


async def draw(client, **arguments):
    result = await client.call_tool("diagram_image", arguments)
    if result.is_error and "No browser to draw in" in result.content[0].text:
        pytest.skip(result.content[0].text)
    assert not result.is_error, result.content[0].text
    return result


async def refused(client, **arguments) -> str:
    result = await client.call_tool("diagram_image", arguments)
    assert result.is_error, result.structured_content
    return result.content[0].text


@pytest.mark.anyio
async def test_a_view_as_png_and_svg(client, tmp_path):
    result = await draw(client, model=SYNTHETIC, view="Overview", format="both", file="report/overview")
    a = result.structured_content
    assert a["title"] == "View: Overview" and a["model"]["name"] == SYNTHETIC
    files = {f["format"]: f for f in a["files"]}
    png, svg = Path(files["png"]["path"]), Path(files["svg"]["path"])
    assert png == tmp_path / "report" / "overview.png" and svg == tmp_path / "report" / "overview.svg"
    assert png.read_bytes()[:8] == PNG and files["png"]["bytes"] == png.stat().st_size
    # scale 2: twice the diagram's size
    assert files["png"]["width"] == 2 * files["svg"]["width"] and files["png"]["height"] == 2 * files["svg"]["height"]
    text = svg.read_text(encoding="utf-8")
    assert text.startswith("<svg") and "<style>" in text and "var(--" not in text  # standalone
    assert "browserLink" in a and a["browserLink"].startswith(BROWSER + "#model=")
    assert len(result.content) == 1  # no preview asked


@pytest.mark.anyio
async def test_the_diagram_of_a_link(client):
    n = await client.call_tool("neighbourhood", {"model": SYNTHETIC, "elements": ["Kafka"]})
    link = n.structured_content["browserLink"]
    result = await draw(client, link=link, format="svg", file="kafka")
    a = result.structured_content
    assert "Kafka" in a["title"] and a["files"][0]["format"] == "svg" and "elements" in a.get("info", "")
    assert "Kafka" in Path(a["files"][0]["path"]).read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_elements_left_to_right_with_a_preview(client):
    tb = (await draw(client, model=SYNTHETIC, elements=["Kafka", "ERP", "Order API"], file="tb")).structured_content
    result = await draw(client, model=SYNTHETIC, elements=["Kafka", "ERP", "Order API"], direction="LR",
                        nesting="composition", file="lr", preview=True)
    lr = result.structured_content
    assert tb["files"][0]["width"] != lr["files"][0]["width"]  # laid out the other way
    assert result.content[1].type == "image" and result.content[1].mime_type == "image/png"
    assert json.loads(result.content[0].text) == lr
    assert "n=1" in lr["browserLink"]


@pytest.mark.anyio
async def test_what_is_refused(client):
    assert "exactly one" in await refused(client, model=SYNTHETIC, view="Overview", elements=["Kafka"])
    assert "exactly one" in await refused(client, model=SYNTHETIC)
    assert "link must be" in await refused(client, link="http://127.0.0.1:8090/#model=1")
    assert "inside the image folder" in await refused(client, model=SYNTHETIC, view="Overview", file="../out")
    assert "No model" in await refused(client, link="#model=no-such-model&d=v~x")
    assert "not in the model" in await refused(client, link="#model=1&d=v~id-no-such-view")


@pytest.mark.anyio
async def test_a_recipe_is_drawn_as_its_diagram(client, api):
    """1.13.0 (API 3.22.0, Browser 2.30.0): a recipe has no drawing; the Browser draws its generated diagram."""
    mid = api.models["synthetic"]
    v = api.call("POST", f"/api/v2/models/{mid}/views", data=json.dumps(
        {"name": "Recipe for images", "recipe": "d=ty~ApplicationComponent"}).encode(), content_type="application/json")
    try:
        a = (await draw(client, model=SYNTHETIC, view=v["id"], format="svg", file="recipe")).structured_content
        assert "Application Component" in a["title"], a
        assert "elements" in a.get("info", "")
    finally:
        api.call("DELETE", f"/api/v2/models/{mid}/views/{v['id']}")


# ---------------------------------------------------------------- 1.17.0 recipe_images

SHOTS = """script "Shots"
for each ApplicationComponent where @Owner = "Finance"
  diagram "Around {name}"
    neighbourhood depth 1
    documentation "Made for {name}"
"""


@pytest.mark.anyio
async def test_images_of_every_diagram_of_a_script(client, tmp_path):
    result = await client.call_tool("recipe_images", {"model": SYNTHETIC, "script": SHOTS, "format": "svg"})
    if result.is_error and "No browser to draw in" in result.content[0].text:
        pytest.skip(result.content[0].text)
    assert not result.is_error, result.content[0].text
    a = result.structured_content
    assert Path(a["folder"]) == tmp_path / "Shots"
    assert [i["name"] for i in a["images"]] == ["Around ERP", "Around ERP Billing", "Around Kafka"]
    first = Path(a["images"][0]["files"][0])
    assert first == tmp_path / "Shots" / "Around_ERP.svg" and "ERP" in first.read_text(encoding="utf-8")
    index = Path(a["index"]).read_text(encoding="utf-8")
    assert index.startswith("# Shots") and "## Around Kafka" in index and "Made for Kafka" in index
    assert "![Around ERP](Around_ERP.svg)" in index


@pytest.mark.anyio
async def test_images_of_a_live_template_and_of_recipes(client, api, tmp_path):
    mid = api.models["synthetic"]
    kept = api.call("POST", f"/api/v2/models/{mid}/recipe-scripts", data=json.dumps(
        {"script": SHOTS.replace('"Shots"', '"Live shots"'), "live": True}).encode(), content_type="application/json")
    v = api.call("POST", f"/api/v2/models/{mid}/views", data=json.dumps(
        {"name": "A recipe", "recipe": "d=ty~ApplicationComponent"}).encode(), content_type="application/json")
    try:
        result = await client.call_tool("recipe_images", {"model": SYNTHETIC, "name": "live shots", "folder": "live",
                                                           "index": False})
        if result.is_error and "No browser to draw in" in result.content[0].text:
            pytest.skip(result.content[0].text)
        a = result.structured_content
        assert len(a["images"]) == 3 and "index" not in a and Path(a["folder"]) == tmp_path / "live"
        assert Path(a["images"][0]["files"][0]).read_bytes()[:8] == PNG
        one = (await client.call_tool("recipe_images", {"model": SYNTHETIC, "views": [v["id"]], "format": "svg"})).structured_content
        assert [i["name"] for i in one["images"]] == ["A recipe"]
        refused = await client.call_tool("recipe_images", {"model": SYNTHETIC, "name": "no such"})
        assert refused.is_error and "no kept recipe script" in refused.content[0].text
        both = await client.call_tool("recipe_images", {"model": SYNTHETIC, "name": "x", "views": [1]})
        assert both.is_error and "exactly one" in both.content[0].text
    finally:
        api.call("DELETE", f"/api/v2/models/{mid}/views/{v['id']}")
        api.call("DELETE", f"/api/v2/models/{mid}/recipe-scripts/{kept['id']}")
