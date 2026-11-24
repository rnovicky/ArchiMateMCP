"""
The tools, one module per subject. Each module has register(server, ctx).

Answers are short: names, types and ids, documentation cut to a few hundred
characters in lists, property values as {name: value}. A list cut at the
limit says so ("truncated") and gives the total, so the assistant can narrow
its question or ask for more.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from app.api_client import ApiClient
from app.config import Settings
from app.links import BrowserLinks, model_token
from app.lookup import Lookup

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

# A reference to a model, element, view, relationship or folder: an id, an XMI identifier, a name or a
# path. Numbers are taken too: clients send an id as a number as often as as a string.
Ref = str | int

# Parameters several tools share
ModelRef = Annotated[Ref | None, Field(
    description="The model: its id or name. May be left out when there is only one model, or a default model is set.")]
Limit = Annotated[int | None, Field(
    description="Most items per list; default and largest value: the server's MAX_RESULTS.", ge=1)]

# Documentation in lists is cut to this many characters; single items give it whole.
SHORT_TEXT = 300


# The API's lists take at most this many ids at once.
IDS_PER_REQUEST = 1000


@dataclass
class Context:
    api: ApiClient
    lookup: Lookup
    settings: Settings
    links: BrowserLinks
    # MCP-15: whether the write tools are offered (D11), and the key's name for the record of changes (D20)
    writable: bool = False
    key_name: str = ""
    # The key's permissions (from /auth/me at start; None when the API was not up): create_model needs "import"
    permissions: list[str] | None = None

    def limit(self, asked: int | None) -> int:
        return min(asked or self.settings.max_results, self.settings.max_results)

    async def browser_link(self, model: dict, diagram: str | None = None, **selection: str) -> dict[str, str]:
        """{"browserLink": url} when BROWSER_URL is set (to merge into an answer), else {}."""
        if not self.links:
            return {}
        url = self.links.url(model_token(model, await self.lookup.models()), diagram, **selection)
        return {"browserLink": url} if url else {}

    async def by_ids(self, model_id: int, kind: str, ids) -> dict[int, dict]:
        """Elements or relationships ("elements", "relationships") by id, fetched in as few requests as can be."""
        wanted = sorted({i for i in ids if i is not None})
        found: dict[int, dict] = {}
        for start in range(0, len(wanted), IDS_PER_REQUEST):
            chunk = wanted[start:start + IDS_PER_REQUEST]
            page = await self.api.get(f"/models/{model_id}/{kind}", ids=",".join(map(str, chunk)), limit=IDS_PER_REQUEST)
            found.update({item["id"]: item for item in page["items"]})
        return found


def short(text: str | None, length: int = SHORT_TEXT) -> str | None:
    if not text:
        return None
    text = " ".join(text.split())
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"


def element_summary(e: dict) -> dict[str, Any]:
    return {"id": e["id"], "name": e.get("name"), "type": e["type"]}


def page(items: list, total: int | None = None) -> dict[str, Any]:
    """A list in an answer: its items, the total, and whether it was cut."""
    total = len(items) if total is None else total
    out: dict[str, Any] = {"total": total, "items": items}
    if total > len(items):
        out["truncated"] = True
    return out


def compact(tool):
    """
    A tool's answer (a dict) as its structured content and, for the assistant to read, as compact JSON:
    the SDK would indent it, which makes the text of a long answer about 1.7 times as long.
    """
    @functools.wraps(tool)
    async def run(*args, **kwargs) -> CallToolResult:
        data = await tool(*args, **kwargs)
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=data)
    return run


def register_all(server: MCPServer, ctx: Context) -> None:
    from app.tools import concepts, folders, graph, history, images, metamodel, models, reports, search, views, write

    for module in (models, search, concepts, views, folders, graph, reports, metamodel, images):
        module.register(server, ctx)
    if ctx.permissions is None or "write" in ctx.permissions:
        history.register(server, ctx)  # the API gives its record of changes to editors (1.7.0)
    if ctx.writable:
        write.register(server, ctx)
