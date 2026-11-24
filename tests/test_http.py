"""The HTTP transport: the token, /health, and the start of an MCP session over HTTP."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from app.http import check_http_settings, http_app
from app.server import build_server

from .api_server import EDITOR_KEY, READER_KEY
from .conftest import make_settings

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
BASE = "http://127.0.0.1:8100"


def app_with(**values):
    s = make_settings(api_url="http://127.0.0.1:9", api_key="k", **values)
    return http_app(build_server(s), s)


def test_token_is_required():
    with TestClient(app_with(mcp_token="secret"), base_url=BASE) as c:
        assert c.post("/mcp", json=INIT, headers=HEADERS).status_code == 401
        assert c.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": "Bearer wrong"}).status_code == 401
        ok = c.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": "Bearer secret"})
        assert ok.status_code == 200, ok.text
        assert "ArchiMate" in ok.text


def test_health_needs_no_token():
    with TestClient(app_with(mcp_token="secret"), base_url=BASE) as c:
        body = c.get("/health").json()
    assert body["status"] == "ok" and body["server"] == "ArchiMate MCP"


def test_loopback_without_token():
    with TestClient(app_with(), base_url=BASE) as c:
        assert c.post("/mcp", json=INIT, headers=HEADERS).status_code == 200


def test_other_hosts_need_a_token_or_client_keys():
    with pytest.raises(SystemExit, match="MCP_TOKEN"):
        check_http_settings(make_settings(host="0.0.0.0"))
    check_http_settings(make_settings(host="0.0.0.0", mcp_token="t"))
    check_http_settings(make_settings(host="0.0.0.0", client_keys=True))
    check_http_settings(make_settings(host="127.0.0.1"))
    with pytest.raises(SystemExit, match="not both"):
        check_http_settings(make_settings(host="0.0.0.0", client_keys=True, mcp_token="t"))


def _tools(c, headers):
    """The tools an HTTP client with these headers is offered (one MCP session)."""
    ok = c.post("/mcp", json=INIT, headers=headers)
    assert ok.status_code == 200, ok.text
    session = {**headers, "Mcp-Session-Id": ok.headers["mcp-session-id"], "Mcp-Protocol-Version": "2025-06-18"}
    c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=session)
    listed = c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=session)
    text = listed.text
    data = json.loads(text[text.index("{"):text.rindex("}") + 1]) if "data:" in text else listed.json()
    return {t["name"] for t in data["result"]["tools"]}


def test_client_keys_each_client_works_with_its_own_key(api):
    from app.__main__ import server_for_client
    from app.http import ClientKeys

    s = make_settings(api_url=api.url, api_key="", client_keys=True, allow_write=True, change_log="")
    with TestClient(ClientKeys(s, server_for_client), base_url=BASE) as c:
        assert c.get("/health").json()["status"] == "ok"
        assert c.post("/mcp", json=INIT, headers=HEADERS).status_code == 401
        wrong = c.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": "Bearer wrong"})
        assert wrong.status_code == 401 and "refused the key" in wrong.json()["error_description"]
        reader = _tools(c, {**HEADERS, "Authorization": f"Bearer {READER_KEY}"})
        editor = _tools(c, {**HEADERS, "Authorization": f"Bearer {EDITOR_KEY}"})
    assert "search" in reader and "create_element" not in reader and "model_history" not in reader
    assert {"create_element", "apply_changes", "model_history"} <= editor, "the write tools follow the client's role"
