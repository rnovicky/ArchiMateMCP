"""python -m app: the client configuration it prints, and stdio started from another folder."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from mcp import Client, StdioServerParameters

from app.__main__ import client_config
from app.config import ROOT

from .api_server import READER_KEY
from .conftest import make_settings


def test_client_config():
    text = client_config(make_settings(), python=r"C:\py\python.exe")
    start = text.index("{")
    desktop = json.loads(text[start:text.index("\n}", start) + 2])
    assert desktop["mcpServers"]["archimate"] == {"command": r"C:\py\python.exe",
                                                  "args": [str(ROOT / "run_server.py"), "stdio"]}
    assert "claude mcp add --transport http archimate --scope user http://127.0.0.1:8100/mcp" in text
    assert "Bearer" not in text
    with_token = client_config(make_settings(mcp_token="s3cret"))
    assert "Bearer <MCP_TOKEN of .env>" in with_token and "s3cret" not in with_token


def test_unknown_command():
    result = subprocess.run([sys.executable, str(ROOT / "run_server.py"), "nonsense"], capture_output=True, text=True)
    assert result.returncode == 2 and "invalid choice" in result.stderr


@pytest.mark.anyio
async def test_stdio_from_another_folder(api, tmp_path):
    """As an MCP client starts it: run_server.py from a foreign working directory."""
    env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "PATH", "TEMP", "TMP")}
    env.update(API_URL=api.url, API_KEY=READER_KEY)
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "run_server.py"), "stdio"],
                                   cwd=str(tmp_path), env=env)
    async with Client(params) as c:
        result = await c.call_tool("api_status", {})
    assert not result.is_error and result.structured_content["role"] == "reader"
