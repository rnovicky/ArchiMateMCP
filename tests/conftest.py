from __future__ import annotations

import pytest

from app.config import Settings

from .api_server import READER_KEY, ApiNotAvailable, TestApi


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_settings(**values) -> Settings:
    """Settings from the arguments only: no .env, no environment variables."""
    class Isolated(Settings):
        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings, *args, **kwargs):
            return (init_settings,)
    return Isolated(**values)


@pytest.fixture(scope="session")
def api():
    """The real ArchiMate API with the synthetic and the basic test model (see api_server.py)."""
    try:
        server = TestApi().start()
    except ApiNotAvailable as e:
        pytest.skip(str(e))
    yield server
    server.stop()


@pytest.fixture
def settings(api) -> Settings:
    """Settings of a server that reads the test API with its reader key."""
    return make_settings(api_url=api.url, api_key=READER_KEY)
