"""The API client against a mocked API: the start-up check and the error messages."""

from __future__ import annotations

import httpx2 as httpx
import pytest

from app.api_client import ApiClient, ApiError, version_tuple
from app.version import MIN_API_VERSION

from .conftest import make_settings

pytestmark = pytest.mark.anyio


def client(handler, **settings) -> ApiClient:
    return ApiClient(make_settings(api_url="http://api.test", api_key="k", **settings), httpx.MockTransport(handler))


def api(version=MIN_API_VERSION, me_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "k"
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "version": version, "apiVersions": ["v2"]})
        if request.url.path == "/api/v2/auth/me":
            if me_status != 200:
                return httpx.Response(me_status, json={"code": "UNAUTHORIZED", "message": "Missing or invalid API key."})
            return httpx.Response(200, json={"name": "mcp", "role": "reader", "permissions": ["read"]})
        return httpx.Response(404, json={"detail": "Not found."})
    return handler


def test_version_tuple():
    assert version_tuple("3.2.0") == (3, 2, 0)
    assert version_tuple("3.10.1rc1") == (3, 10, 1)
    assert version_tuple("3.10.0") > version_tuple("3.9.9")
    assert version_tuple("") == ()


async def test_check_passes():
    status = await client(api()).check()
    assert (status.version, status.key_name, status.role) == (MIN_API_VERSION, "mcp", "reader")


async def test_check_refuses_an_old_api():
    with pytest.raises(ApiError, match=f"3.0.9; this server needs {MIN_API_VERSION}"):
        await client(api(version="3.0.9")).check()


async def test_check_refuses_a_wrong_key():
    with pytest.raises(ApiError, match="refused the key") as e:
        await client(api(me_status=401)).check()
    assert e.value.status == 401


async def test_check_without_a_key():
    c = ApiClient(make_settings(api_url="http://api.test"), httpx.MockTransport(api()))
    with pytest.raises(ApiError, match="No API key"):
        await c.check()


async def test_unreachable_api():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)
    with pytest.raises(ApiError, match="cannot be reached") as e:
        await client(handler).get("/models")
    assert e.value.status is None


async def test_validation_errors_are_readable():
    def handler(request):
        return httpx.Response(422, json={"detail": [{"loc": ["query", "limit"], "msg": "must be <= 1000"}]})
    with pytest.raises(ApiError, match="422: query.limit: must be <= 1000"):
        await client(handler).get("/models", limit=5000)


async def test_the_apis_error_format():
    def handler(request):
        if request.url.path.endswith("search"):
            return httpx.Response(422, json={"code": "VALIDATION_ERROR", "message": "Request validation failed.",
                                             "details": ["query → elementTypes: unknown type Nonsense"]})
        return httpx.Response(404, json={"code": "NOT_FOUND", "message": "Element 99 not found."})
    with pytest.raises(ApiError) as e:
        await client(handler).get("/models/1/search")
    assert str(e.value) == "422: Request validation failed. query → elementTypes: unknown type Nonsense"
    with pytest.raises(ApiError, match=r"^404: Element 99 not found\.$"):
        await client(handler).get("/models/1/elements/99")


async def test_none_parameters_are_left_out():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json={"items": []})
    assert await client(handler).get("/models", limit=10, q=None) == {"items": []}
    assert seen == {"limit": "10"}


async def test_whether_the_write_tools_are_offered(caplog):
    """D11: ALLOW_WRITE and a key that may write; a key that may write without ALLOW_WRITE is warned about."""
    from app.__main__ import _start_check, may_write

    def with_role(role, permissions):
        def handler(request):
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok", "version": MIN_API_VERSION, "apiVersions": ["v2"]})
            return httpx.Response(200, json={"name": "k", "role": role, "permissions": permissions})
        return handler

    editor = await _start_check(client(with_role("editor", ["read", "write"])))
    reader = await _start_check(client(with_role("reader", ["read"])))
    on, off = make_settings(api_key="k", allow_write=True), make_settings(api_key="k")
    with caplog.at_level("WARNING"):
        assert may_write(on, editor) is True
        assert may_write(off, editor) is False
        assert "has the role editor, but writing is off" in caplog.text
        assert may_write(on, reader) is False
        assert "which may not write" in caplog.text
    assert may_write(on, None) is True, "the API not up yet: offered, the API decides"
    assert may_write(off, None) is False
