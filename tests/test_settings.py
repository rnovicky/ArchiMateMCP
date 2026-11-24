"""Settings: .env.example names every one, and .env may hold no others."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from app.config import ROOT, Settings

from .conftest import make_settings


def _example_keys() -> set[str]:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    return {m.group(1).lower() for m in re.finditer(r"^#?([A-Z][A-Z0-9_]*)=", text, re.MULTILINE)}


def test_env_example_names_every_setting():
    assert _example_keys() == set(Settings.model_fields)


def test_unknown_setting_in_env_file_is_refused(tmp_path):
    env = tmp_path / ".env"
    env.write_text("API_KEY=x\nNO_SUCH_SETTING=1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        Settings(_env_file=env)


def test_defaults():
    s = make_settings()
    assert (s.api_url, s.host, s.port, s.mcp_token) == ("http://127.0.0.1:8000", "127.0.0.1", 8100, "")
    assert make_settings(api_url="http://h:1/").api_base == "http://h:1/api/v2"
