"""MCP-35 (1.12.0) diagram_image: a diagram as an SVG or PNG file, drawn by the ArchiMate Browser (app/render.py)."""

from __future__ import annotations

import atexit
import base64
import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import Field

from app.config import Settings
from app.links import BrowserLinks, model_token
from app.render import Renderer, RenderError
from app.tools import Context, ModelRef, Ref

# It writes files (and may replace one of the same name), but changes no model
WRITES_FILES = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

# Links to the Browser are built for the render page, whatever BROWSER_URL is (only the part after '#' is used)
_LINKS = BrowserLinks("http://render.invalid/")

# The nesting of generated diagrams as the Browser's links carry it (n=, js/app/diagram.js nestingMode)
NESTING = {"none": "0", "composition": "1", "assignment": "2"}

# One renderer for the whole process (with CLIENT_KEYS every client has a server of its own; they share it)
_renderer: Renderer | None = None


def renderer(settings: Settings) -> Renderer:
    global _renderer
    if _renderer is None:
        _renderer = Renderer(settings)
        atexit.register(_renderer.close)
    return _renderer


def safe_name(text: str) -> str:
    """A file name from a diagram's title (as the Browser's downloads name them)."""
    return re.sub(r"[^\w.-]+", "_", text or "diagram").strip("._")[:80] or "diagram"


def target(settings: Settings, file: str | None, title: str) -> Path:
    """The file to write, without its extension: `file` inside IMAGE_DIR (sub-folders allowed), or the title."""
    root = settings.image_path
    name = (file or "").strip() or safe_name(title)
    path = Path(name)
    if path.suffix.lower() in (".png", ".svg"):
        path = path.with_suffix("")
    full = (root / path).resolve()
    if not full.is_relative_to(root) or full == root:
        raise ToolError(f"file must name a file inside the image folder {root} (IMAGE_DIR), e.g. \"report/overview\".")
    return full


def link_hash(link: str) -> str:
    """The part of a Browser link after '#' (a whole link, '#…' or the parameters alone)."""
    text = link.strip()
    hash_ = text.split("#", 1)[1] if "#" in text else text
    if "model=" not in hash_ or not ("d=" in hash_ or "view=" in hash_):
        raise ToolError("link must be a link to a diagram in the ArchiMate Browser (a \"browserLink\" of another "
                        "tool's answer, with model= and d=).")
    return hash_


def register(server: MCPServer, ctx: Context) -> None:
    lookup = ctx.lookup

    @server.tool(annotations=WRITES_FILES)
    async def diagram_image(
        model: ModelRef = None,
        view: Annotated[Ref | None, Field(description="A view to draw, as it is stored: its id, XMI identifier or name.")] = None,
        elements: Annotated[list[Ref] | None, Field(
            description="Elements to draw, with the relationships between them, laid out automatically.")] = None,
        link: Annotated[str | None, Field(description=(
            "A \"browserLink\" from another tool's answer (neighbourhood, impact_analysis, find_paths, subgraph, "
            "propose_view, search…): the diagram it opens, drawn as the Browser draws it. Its model is used."))] = None,
        format: Annotated[Literal["png", "svg", "both"], Field(description=(
            "png (default; for documents), svg (sharp at any size, for HTML and recent Word), or both."))] = "png",
        file: Annotated[str | None, Field(description=(
            "File name without extension, inside the server's image folder; sub-folders are allowed "
            "(\"report/overview\"). Default: the diagram's title. A file of the same name is replaced."))] = None,
        direction: Annotated[Literal["TB", "LR"], Field(
            description="A generated diagram top to bottom (TB, default) or left to right (LR).")] = "TB",
        nesting: Annotated[Literal["none", "composition", "assignment"] | None, Field(description=(
            "A generated diagram with nested boxes: composition (Composition and Aggregation drawn as boxes inside "
            "boxes), assignment (Assignment too), or none. Default: the link's own, else none."))] = None,
        scale: Annotated[float, Field(description="PNG pixels per diagram unit: 2 (default) is sharp in print.",
                                      ge=0.5, le=4)] = 2,
        preview: Annotated[bool, Field(description=(
            "Also return a small PNG for you to look at (it takes room in your context; the files are what "
            "go into a document)."))] = False,
    ) -> CallToolResult:
        """Save a diagram as an image file (PNG or SVG), drawn exactly as the ArchiMate Browser draws it: a stored
        view with its layout, or a generated diagram laid out automatically.

        For reports and documents: give exactly one of view, elements or link, then put the file the answer
        names into the document. A link from neighbourhood, impact_analysis, find_paths, subgraph or
        propose_view gives that diagram with the Browser's rules. The answer has the file's path, the diagram's
        title and its size. The first image takes a few seconds (the server starts a browser without a window);
        the next ones about a second each.
        """
        if sum(x is not None for x in (view, elements, link)) != 1:
            raise ToolError("Give exactly one of view, elements and link.")
        if link is not None:
            hash_ = link_hash(link)
            m = None
        else:
            m = await lookup.model(model)
            token = model_token(m, await lookup.models())
            if view is not None:
                v = await lookup.view(m["id"], view)
                url = _LINKS.url(token, _LINKS.view(v))
            else:
                if not elements:
                    raise ToolError("elements is empty.")
                chosen: dict[int, dict] = {}
                for ref in elements:
                    e = await lookup.element(m["id"], ref)
                    chosen.setdefault(e["id"], e)
                url = _LINKS.url(token, _LINKS.elements(list(chosen.values())))
            hash_ = url.split("#", 1)[1]
        if nesting is not None and "view=" not in hash_ and "d=v~" not in hash_:
            hash_ = re.sub(r"(^|&)n=[^&]*", "", hash_) + f"&n={NESTING[nesting]}"

        formats = ("svg", "png") if format == "both" else (format,)
        try:
            image = await renderer(ctx.settings).render(hash_, ctx.settings.api_key, formats=formats,
                                                        direction=direction, png_scale=scale, preview=preview)
        except RenderError as e:
            raise ToolError(str(e)) from None

        base = target(ctx.settings, file, image.title)
        base.parent.mkdir(parents=True, exist_ok=True)
        files: list[dict[str, Any]] = []
        if image.svg is not None:
            path = base.with_name(base.name + ".svg")
            path.write_text(image.svg, encoding="utf-8")
            files.append({"format": "svg", "path": str(path), "width": image.width, "height": image.height,
                          "bytes": path.stat().st_size})
        if image.png is not None:
            path = base.with_name(base.name + ".png")
            path.write_bytes(image.png)
            width, height = image.png_size or (image.width, image.height)
            files.append({"format": "png", "path": str(path), "width": width, "height": height,
                          "bytes": len(image.png)})
        answer: dict[str, Any] = {"title": image.title, "files": files}
        if m is not None:
            answer["model"] = {"id": m["id"], "name": m["name"]}
        if image.info:
            answer["info"] = image.info
        if image.notes:
            answer["notes"] = image.notes
        if ctx.links:
            answer["browserLink"] = ctx.links.base + "#" + hash_
        content: list[Any] = [TextContent(type="text", text=json.dumps(answer, ensure_ascii=False, separators=(",", ":")))]
        if image.preview is not None:
            content.append(ImageContent(type="image", data=base64.b64encode(image.preview).decode(), mime_type="image/png"))
        return CallToolResult(content=content, structured_content=answer)
