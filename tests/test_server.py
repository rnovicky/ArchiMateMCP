"""The server against the real API, through an in-process MCP client."""

from __future__ import annotations

import pytest
from mcp import Client

from app.server import build_server
from app.version import APP_VERSION

from .conftest import make_settings

pytestmark = pytest.mark.anyio


async def test_tools_are_listed_and_read_only(settings):
    async with Client(build_server(settings)) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert "api_status" in tools
        # diagram_image (1.12.0) writes image files, but changes no model
        assert all(t.annotations and t.annotations.read_only_hint for n, t in tools.items() if n not in ("diagram_image", "recipe_images"))
        assert not tools["diagram_image"].annotations.read_only_hint and not tools["diagram_image"].annotations.destructive_hint
        assert c.instructions and "ArchiMate" in c.instructions


async def test_api_status(settings, api):
    async with Client(build_server(settings)) as c:
        result = await c.call_tool("api_status", {})
    assert not result.is_error
    status = result.structured_content
    assert status["apiVersion"]
    assert {k: v for k, v in status.items() if k != "apiVersion"} == {
        "server": f"ArchiMate MCP {APP_VERSION}", "apiUrl": api.url, "keyName": "mcp-tests-reader", "role": "reader",
        "writing": False, "clientKeys": False, "keyLabel": None, "requireIfMatch": api.require_if_match,
    }


async def test_api_errors_reach_the_assistant(api):
    async with Client(build_server(make_settings(api_url=api.url, api_key="wrong"))) as c:
        result = await c.call_tool("api_status", {})
    assert result.is_error
    assert "refused the key" in result.content[0].text
