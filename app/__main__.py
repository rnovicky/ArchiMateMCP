"""
python -m app [stdio | http | check | config]

  stdio   (default) serve one MCP client over stdin/stdout; the client starts it
  http    serve MCP clients over HTTP at http://HOST:PORT/mcp
  check   check that the ArchiMate API answers, is new enough and takes the key
  config  print how to add this server to Claude Desktop and Claude Code

Over stdio, stdout belongs to the protocol: everything else goes to stderr.
"""

from __future__ import annotations

import argparse
import json
import logging
import socket
import sys

import anyio

from app.api_client import ApiClient, ApiError, ApiStatus
from app.config import LOOPBACK_HOSTS, ROOT, Settings, load_settings
from app.version import APP_VERSION

logger = logging.getLogger("app")


async def _check(settings: Settings) -> int:
    client = ApiClient(settings)
    try:
        status = await client.check()
    except ApiError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    finally:
        await client.aclose()
    print(f"ArchiMate API {status.version} at {status.url}: key \"{status.key_name}\", role {status.role}.")
    return 0


async def _start_check(client: ApiClient) -> ApiStatus | None:
    """At start: stop for a wrong key or an old API; only warn when the API is not up yet (then None)."""
    try:
        status = await client.check()
    except ApiError as e:
        if e.status is None and "cannot be reached" in str(e):
            logger.warning("%s The tools will fail until it answers.", e)
            return None
        raise SystemExit(f"ArchiMate MCP cannot start: {e}") from e
    finally:
        await client.aclose()
    logger.info("ArchiMate API %s at %s, key \"%s\" (%s).", status.version, status.url, status.key_name, status.role)
    return status


def may_write(settings: Settings, status: ApiStatus | None) -> bool:
    """D11: the write tools need ALLOW_WRITE and a key that may write (unknown while the API is down: offered)."""
    if not settings.allow_write:
        if status is not None and "write" in status.permissions:
            logger.warning("The key \"%s\" has the role %s, but writing is off (ALLOW_WRITE): a key with the role "
                           "reader is enough (the API's README, \"API keys and roles\").", status.key_name, status.role)
        return False
    if status is not None and "write" not in status.permissions:
        logger.warning("ALLOW_WRITE is on, but the key \"%s\" has the role %s, which may not write: the write tools "
                       "are not offered. Give the server a key with the role editor.", status.key_name, status.role)
        return False
    logger.info("Writing is on: the write tools are offered.")
    return True


def _build(settings: Settings):
    from app.server import build_server

    client = ApiClient(settings)
    status = anyio.run(_start_check, client)
    return build_server(settings, client, writable=may_write(settings, status),
                        key_name=status.key_name if status else "", permissions=status.permissions if status else None)


async def server_for_client(settings: Settings):
    """CLIENT_KEYS (MU-2): a server around one client's key, after the API has said whose key it is."""
    from app.server import build_server

    client = ApiClient(settings)
    status = await client.check()
    writable = settings.allow_write and "write" in status.permissions
    return build_server(settings, client, writable=writable, key_name=status.key_name,
                        permissions=status.permissions), status


async def _version_check(settings: Settings) -> None:
    """CLIENT_KEYS: at start only the API's version is checked; each client's key when it comes."""
    client = ApiClient(settings)
    try:
        version = await client.check_version()
        logger.info("ArchiMate API %s at %s; every client sends its own key (CLIENT_KEYS).", version, settings.api_url)
    except ApiError as e:
        if e.status is None and "cannot be reached" in str(e):
            logger.warning("%s Clients will be refused until it answers.", e)
            return
        raise SystemExit(f"ArchiMate MCP cannot start: {e}") from e
    finally:
        await client.aclose()


def _stdio(settings: Settings) -> None:
    _build(settings).run("stdio")


def _loopback_sockets(port: int) -> list[socket.socket]:
    """127.0.0.1 and ::1 on the same port, as the API's launcher does (localhost is ::1 first on Windows)."""
    def bound(family: socket.AddressFamily, host: str, port: int) -> socket.socket:
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            sock.bind((host, port))
        except OSError:
            sock.close()
            raise
        return sock

    ipv4 = bound(socket.AF_INET, "127.0.0.1", port)
    sockets = [ipv4]
    try:
        sockets.append(bound(socket.AF_INET6, "::1", ipv4.getsockname()[1]))
    except OSError as e:
        logger.warning("Cannot listen on [::1] (%s); continuing with 127.0.0.1 only.", e)
    return sockets


def _http(settings: Settings) -> None:
    import uvicorn

    from app.http import MCP_PATH, check_http_settings, http_app

    check_http_settings(settings)
    if settings.client_keys:
        from app.http import ClientKeys

        anyio.run(_version_check, settings)
        app = ClientKeys(settings, server_for_client)
        note = " (each client with its own API key)"
    else:
        app = http_app(_build(settings), settings)
        note = "" if settings.mcp_token else " (no MCP_TOKEN: loopback only)"
    shown = "127.0.0.1" if settings.host in LOOPBACK_HOSTS else settings.host
    logger.info("ArchiMate MCP %s at http://%s:%s%s%s", APP_VERSION, shown, settings.port, MCP_PATH, note)
    config = uvicorn.Config(app, host=settings.host, port=settings.port, log_level="info")
    try:
        if settings.host in LOOPBACK_HOSTS:
            uvicorn.Server(config).run(sockets=_loopback_sockets(settings.port))
        else:
            uvicorn.Server(config).run()
    except KeyboardInterrupt:
        # Ctrl+C: the server has already shut down cleanly
        pass


def client_config(settings: Settings, python: str | None = None) -> str:
    """How to register the server: Claude Desktop (stdio) and Claude Code (stdio or HTTP)."""
    python = python or sys.executable
    script = str(ROOT / "run_server.py")
    desktop = {"mcpServers": {"archimate": {"command": python, "args": [script, "stdio"]}}}
    host = "127.0.0.1" if settings.host in LOOPBACK_HOSTS else settings.host
    url = f"http://{host}:{settings.port}/mcp"
    header = (' --header "Authorization: Bearer <your own key of the ArchiMate API>"' if settings.client_keys
              else ' --header "Authorization: Bearer <MCP_TOKEN of .env>"' if settings.mcp_token else "")
    return "\n".join([
        "Claude Desktop - add to claude_desktop_config.json (Settings > Developer > Edit Config):",
        "",
        json.dumps(desktop, indent=2),
        "",
        "Claude Code - over stdio (Claude Code starts the server):",
        "",
        f'  claude mcp add archimate --scope user -- "{python}" "{script}" stdio',
        "",
        "Claude Code - over HTTP (the server runs on its own: archimatemcp.bat start):",
        "",
        f"  claude mcp add --transport http archimate --scope user {url}{header}",
        "",
        ("Over HTTP with CLIENT_KEYS each client sends its own API key; over stdio the server reads API_URL and "
         "API_KEY from " + str(ROOT / ".env") + ": put your own key there.") if settings.client_keys else
        "The server reads API_URL and API_KEY from " + str(ROOT / ".env") + "; no key goes into the client's settings.",
    ])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app", description="ArchiMate MCP " + APP_VERSION)
    parser.add_argument("command", nargs="?", default="stdio", choices=["stdio", "http", "check", "config"])
    args = parser.parse_args(argv)
    # stderr only: over stdio, stdout carries the protocol
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    # One line per request to the API is too much; its errors reach the tools anyway
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    try:
        settings = load_settings()
    except Exception as e:  # an unknown or invalid setting in .env
        raise SystemExit(f"ArchiMate MCP: the settings are not valid (.env in {ROOT}):\n{e}") from e

    if args.command == "check":
        raise SystemExit(anyio.run(_check, settings))
    if args.command == "config":
        print(client_config(settings))
        return
    try:
        _http(settings) if args.command == "http" else _stdio(settings)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
