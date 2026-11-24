"""MU-15 (1.11.0): resources that announce their change, from the API's change events (3.17.0), against the real API."""

from __future__ import annotations

import json
import uuid
import warnings

import anyio
import pytest
from mcp import Client
from mcp.shared.subscriptions import ResourceUpdated

from app.server import build_server

pytestmark = pytest.mark.anyio


def _admin(api, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    return api.call(method, "/api/v2" + path, data=data, content_type="application/json" if data else None)


@pytest.fixture
def model(api):
    """A model of its own with one element; deleted afterwards."""
    m = _admin(api, "POST", "/models", {"xmiIdentifier": f"id-{uuid.uuid4().hex}", "name": f"Watch {uuid.uuid4().hex[:6]}"})
    done = _admin(api, "POST", f"/models/{m['id']}/changes", {"operations": [
        {"op": "createElement", "type": "BusinessActor", "name": "Watched"}]})
    m["element"] = done["results"][0]["id"]
    m["uri"] = f"archimate://models/{m['id']}/elements/{m['element']}"
    yield m
    _admin(api, "DELETE", f"/models/{m['id']}")


def _rename(api, model: dict, name: str) -> None:
    _admin(api, "PUT", f"/models/{model['id']}/elements/{model['element']}", {"name": name})


async def test_a_listen_stream_is_told_when_a_subscribed_resource_changes(api, model, settings):
    server = build_server(settings)
    other = _admin(api, "POST", "/models", {"xmiIdentifier": f"id-{uuid.uuid4().hex}", "name": "Watch other"})
    try:
        async with Client(server) as client:
            assert server.watcher._task is None, "nobody subscribed: no stream"
            async with client.listen(resource_subscriptions=[model["uri"]]) as sub:
                await anyio.sleep(1.5)  # the stream to the API opens
                assert server.watcher._task is not None
                _admin(api, "POST", f"/models/{other['id']}/changes", {"operations": [
                    {"op": "createElement", "type": "BusinessActor", "name": "Elsewhere"}]})
                _rename(api, model, "Watched, renamed")
                with anyio.fail_after(8):
                    event = await sub.__anext__()
                assert event == ResourceUpdated(uri=model["uri"]), "only the subscribed resource, by its model's change"
            await anyio.sleep(0.2)
            assert not server.watcher.subscriptions and server.watcher._task is None, "the stream let go"
    finally:
        _admin(api, "DELETE", f"/models/{other['id']}")


async def test_the_list_of_models_is_told_of_every_model(api, model, settings):
    server = build_server(settings)
    async with Client(server) as client:
        async with client.listen(resource_subscriptions=["archimate://models", "archimate://metamodel"]) as sub:
            await anyio.sleep(1.5)
            _rename(api, model, "Watched again")
            with anyio.fail_after(8):
                event = await sub.__anext__()
            assert event == ResourceUpdated(uri="archimate://models")


async def test_an_older_client_subscribes_with_resources_subscribe(api, model, settings):
    told: list[str] = []

    async def handler(message):
        params = getattr(getattr(message, "root", message), "params", None)
        if getattr(message, "method", None) == "notifications/resources/updated" or (
                params is not None and type(params).__name__ == "ResourceUpdatedNotificationParams"):
            told.append(str(params.uri))

    server = build_server(settings)
    async with Client(server, mode="legacy", message_handler=handler) as client:
        assert client.session.server_capabilities.resources.subscribe is True
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            await client.subscribe_resource(model["uri"])
        await anyio.sleep(1.5)
        _rename(api, model, "Watched by an older client")
        with anyio.fail_after(8):
            while not told:
                await anyio.sleep(0.1)
        # changes from just before the stream opened may be told too (the API reads its record once a second)
        assert set(told) == {model["uri"]}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            await client.unsubscribe_resource(model["uri"])
        assert not server.watcher.subscriptions
