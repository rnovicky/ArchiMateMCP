"""
MCP-35 (1.12.0) diagram_image: a diagram as an SVG or PNG file, drawn by the ArchiMate Browser (app/render.py).

1.17.0 recipe_images: an image of each diagram of a recipe script (its text, a kept or live script, or chosen
recipes), into one folder, with an index for a report.
"""

from __future__ import annotations

import atexit
import base64
import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import Field

from app.config import Settings
from app.api_client import ApiError
from app.links import BrowserLinks, model_token
from app.render import Renderer, RenderError
from app.tools import Context, ModelRef, Ref

# It writes files (and may replace one of the same name), but changes no model
WRITES_FILES = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

# Links to the Browser are built for the render page, whatever BROWSER_URL is (only the part after '#' is used)
_LINKS = BrowserLinks("http://render.invalid/")

# The nesting of generated diagrams as the Browser's links carry it (n=, js/app/diagram.js nestingMode)
NESTING = {"none": "0", "composition": "1", "assignment": "2"}

# The most images recipe_images draws in one call
IMAGES_MAX = 100

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

    @server.tool(annotations=WRITES_FILES)
    async def recipe_images(
        model: ModelRef = None,
        script: Annotated[str | None, Field(description=(
            "The text of a recipe script: an image of each diagram it makes (it need not have run)."), max_length=100_000)] = None,
        name: Annotated[Ref | None, Field(description=(
            "A kept recipe script or live template (recipe_scripts lists them): an image of each diagram it makes "
            "from the model as it is now."))] = None,
        views: Annotated[list[Ref] | None, Field(description="Recipes (views that are recipes): an image of each.")] = None,
        format: Annotated[Literal["png", "svg", "both"], Field(description="png (default), svg, or both.")] = "png",
        folder: Annotated[str | None, Field(description=(
            "Folder inside the server's image folder (IMAGE_DIR) for the files; default: the script's name, or "
            "\"recipes\". Files of the same name are replaced."))] = None,
        index: Annotated[bool, Field(description=(
            "Also write index.md: each diagram's name, documentation and image, ready to go into a report."))] = True,
        direction: Annotated[Literal["TB", "LR"], Field(description="Top to bottom (TB, default) or left to right.")] = "TB",
        scale: Annotated[float, Field(description="PNG pixels per diagram unit: 2 (default) is sharp in print.",
                                      ge=0.5, le=4)] = 2,
    ) -> dict[str, Any]:
        """Save an image of each diagram of a recipe script, drawn as the ArchiMate Browser draws it, into one
        folder: for a report with many diagrams ("the neighbourhood of every application with Status Live"). Give
        exactly one of script (its text; check it with check_recipe_script first), name (a kept script or live
        template) or views (recipes). At most 100 images at once. The answer lists the files; index.md lists them
        with their names and documentation."""
        if sum(x is not None for x in (script, name, views)) != 1:
            raise ToolError("Give exactly one of script, name and views.")
        m = await lookup.model(model)
        api = ctx.api
        items: list[dict[str, Any]] = []  # name, documentation, recipe
        title = "recipes"
        try:
            if script is not None:
                report = await api.post(f"/models/{m['id']}/recipe-scripts/check", {"script": script})
                if report.get("errors"):
                    raise ToolError("The script has errors (check_recipe_script lists them with their lines): "
                                    + "; ".join(f"line {e['line']}: {e['message']}" for e in report["errors"][:5]))
                items, title = report.get("recipes", []), report.get("script") or title
            elif name is not None:
                listed = await api.get(f"/models/{m['id']}/recipe-scripts")
                wanted = str(name).strip()
                found = [x for x in listed if x["name"] == wanted] or [x for x in listed if x["name"].casefold() == wanted.casefold()] \
                    or [x for x in listed if str(x.get("id")) == wanted]
                if not found or not found[0].get("stored"):
                    raise ToolError(f"The model has no kept recipe script \"{wanted}\" (recipe_scripts lists them); for "
                                    "the recipes of a script whose text is not kept, give views.")
                expanded = await api.get(f"/models/{m['id']}/recipe-scripts/{found[0]['id']}/recipes")
                if expanded.get("errors"):
                    raise ToolError("The model no longer fits the script: "
                                    + "; ".join(f"line {e['line']}: {e['message']}" for e in expanded["errors"][:5]))
                items, title = expanded.get("recipes", []), found[0]["name"]
            else:
                for ref in views or []:
                    v = await lookup.view(m["id"], ref)
                    if v.get("recipe") is None:
                        raise ToolError(f"View \"{v.get('name')}\" is not a recipe; diagram_image draws a stored view.")
                    items.append({"name": v["name"], "documentation": v.get("documentation"), "recipe": v["recipe"]})
        except ApiError as e:
            if e.status in (404, 405) and "recipe script" not in str(e).lower():
                raise ToolError("Images of recipe scripts need ArchiMate API 3.24.0 (a kept script 3.26.0) or later.") from e
            raise
        if not items:
            raise ToolError("Nothing to draw: the script makes no diagram now.")
        if len(items) > IMAGES_MAX:
            raise ToolError(f"{len(items)} diagrams; at most {IMAGES_MAX} images at once. Narrow the script (max, where).")

        root = target(ctx.settings, folder, title)
        root.mkdir(parents=True, exist_ok=True)
        token = quote(model_token(m, await lookup.models()), safe="-*@:~.")
        formats = ("svg", "png") if format == "both" else (format,)
        used: set[str] = set()
        done: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        for item in items:
            base = safe_name(item["name"])
            stem, n = base, 2
            while stem.lower() in used:
                stem, n = f"{base}_{n}", n + 1
            used.add(stem.lower())
            try:
                image = await renderer(ctx.settings).render(f"model={token}&{item['recipe']}", ctx.settings.api_key,
                                                            formats=formats, direction=direction, png_scale=scale,
                                                            preview=False)
            except RenderError as e:
                failed.append({"name": item["name"], "error": str(e)})
                continue
            files = []
            if image.svg is not None:
                path = root / f"{stem}.svg"
                path.write_text(image.svg, encoding="utf-8")
                files.append(str(path))
            if image.png is not None:
                path = root / f"{stem}.png"
                path.write_bytes(image.png)
                files.append(str(path))
            done.append({"name": item["name"], "files": files, "documentation": item.get("documentation"),
                         "stem": stem, **({"notes": image.notes} if image.notes else {})})
        answer: dict[str, Any] = {"model": {"id": m["id"], "name": m["name"]}, "folder": str(root),
                                  "images": [{k: v for k, v in d.items() if k not in ("stem", "documentation")} for d in done]}
        if failed:
            answer["failed"] = failed
        if index and done:
            ext = "png" if "png" in formats else "svg"
            lines = [f"# {title}", ""]
            for d in done:
                lines += [f"## {d['name']}", ""]
                if d.get("documentation"):
                    lines += [d["documentation"], ""]
                lines += [f"![{d['name']}]({quote(d['stem'])}.{ext})", ""]
            path = root / "index.md"
            path.write_text("\n".join(lines), encoding="utf-8")
            answer["index"] = str(path)
        return answer
