"""
Links that open a diagram in the ArchiMate Browser (MCP-11, decision D7).

The browser keeps a diagram's definition in the URL hash: `model=` names the
model, `d=` the diagram, `element=` (or `view=`, `folder=`) what is selected.
Items are named by XMI identifier, so that a link survives a replace of the
model; see the browser's README, "Basket and shareable diagram links", and
its js/refs.js and encodeDef() in js/app.js, which this follows.
"""

from __future__ import annotations

import re
from urllib.parse import quote

# The browser's layer keys (js/archimate.js) by the API's layer key
LAYER_KEYS = {
    "Strategy": "strategy", "Business": "business", "Application": "application", "Technology": "technology",
    "Physical": "physical", "Motivation": "motivation", "ImplementationMigration": "implementation", "Other": "other",
}
# The relationship types an impact diagram follows by default (the browser's DEFAULT_TYPES, js/impact.js)
IMPACT_DEFAULT_TYPES = {"Serving", "Realization", "Assignment", "Composition", "Aggregation", "Access", "Flow",
                        "Triggering"}
# The deepest neighbourhood the browser draws
NEIGHBOURHOOD_MAX_DEPTH = 3

_KEEP = re.compile(r"[A-Za-z0-9-]")


def escape_ref(xmi: str) -> str:
    """An XMI identifier as a link token: letters, digits and '-' stay; any other character is '*' and hex per byte."""
    out = []
    for ch in xmi:
        if _KEEP.fullmatch(ch):
            out.append(ch)
        else:
            out.extend(f"*{b:02X}" for b in ch.encode("utf-8"))
    return "".join(out)


def token(item: dict) -> str:
    """The token of an item: its escaped XMI identifier, or its id when it has none (or one of digits only)."""
    xmi = item.get("xmiIdentifier")
    return escape_ref(xmi) if xmi and not str(xmi).isdigit() else str(item["id"])


def model_token(model: dict, models: list[dict]) -> str:
    """Models that share an XMI identifier are named by id (API 2.10.0), the others by identifier."""
    xmi = model.get("xmiIdentifier")
    if xmi and sum(1 for m in models if m.get("xmiIdentifier") == xmi) > 1:
        return str(model["id"])
    return token(model)


def folder_token(tree: list[dict], folder_id: int) -> str:
    """
    A folder in a folder tree: its identifier; else its path of labels ("@Application:ERP*20domain") when
    that names it alone (the API takes the first of sibling folders with the same label); else its id.
    """
    def find(nodes: list[dict], chain: list[tuple[dict, list[dict]]]):
        for node in nodes:
            here = chain + [(node, nodes)]
            if node["id"] == folder_id:
                return here
            found = find(node.get("children", []), here)
            if found:
                return found
        return None

    chain = find(tree, []) or []
    if not chain:
        return str(folder_id)
    folder = chain[-1][0]
    if folder.get("xmiIdentifier"):
        return token(folder)
    for node, siblings in chain:
        first = next(s for s in siblings if s.get("label") == node.get("label"))
        if not node.get("label") or first["id"] != node["id"]:
            return str(folder_id)
    return "@" + ":".join(escape_ref(node["label"]) for node, _ in chain)


class BrowserLinks:
    def __init__(self, base_url: str):
        self.base = base_url.strip().rstrip("/") + "/" if base_url.strip() else ""

    def __bool__(self) -> bool:
        return bool(self.base)

    def url(self, model_ref: str, diagram: str | None = None, **selection: str) -> str | None:
        if not self.base:
            return None
        parts = [f"model={quote(model_ref, safe='-*@:~.')}"]
        parts += [f"{kind}={quote(ref, safe='-*@:~.')}" for kind, ref in selection.items() if ref]
        if diagram:
            parts.append(f"d={quote(diagram, safe='-*@:~.')}")
        return self.base + "#" + "&".join(parts)

    def recipe_url(self, model_ref: str, recipe: str) -> str | None:
        """1.15.0: the link of a recipe (the parameters of a Browser link as the API stores them, already encoded)."""
        if not self.base:
            return None
        return f"{self.base}#model={quote(model_ref, safe='-*@:~.')}&{recipe}"

    # ---------------------------------------------------------------- diagram definitions (encodeDef)

    @staticmethod
    def elements(items: list[dict]) -> str:
        return "el~" + ".".join(token(e) for e in items)

    @staticmethod
    def view(view: dict) -> str:
        return "v~" + token(view)

    @staticmethod
    def explore(elements: list[dict], hidden: list[dict]) -> str:
        """MCP-28: these elements, without the relationships `hidden` (the browser's explorer diagram, "ex~")."""
        tail = "~" + ".".join(token(r) for r in hidden) if hidden else ""
        return "ex~~" + ".".join(token(e) for e in elements) + tail

    @staticmethod
    def neighbourhood(seeds: list[dict], depth: int, direction: str,
                      incoming_types: list[str] | None = None, outgoing_types: list[str] | None = None) -> str | None:
        """nb~…; 1.15.0 (Browser 2.33.0): with the relationship types followed per direction, ~<b|o|i>~<in>~<out>."""
        if depth > NEIGHBOURHOOD_MAX_DEPTH:
            return None
        code = {"out": "o", "in": "i"}.get(direction, "")
        head = f"nb~{depth}~" + ".".join(token(e) for e in seeds)
        inc = incoming_types if direction != "out" else None
        out = outgoing_types if direction != "in" else None
        if inc is not None or out is not None:
            if inc == [] or out == []:
                return None  # a direction followed by no type: the Browser says so with the direction itself
            return f"{head}~{code or 'b'}~{'.'.join(inc or [])}~{'.'.join(out or [])}"
        return head + (f"~{code}" if code else "")

    @staticmethod
    def impact(starts: list[dict], direction: str, depth: int, types: list[str] | None) -> str:
        chosen = [t for t in (types or []) if t]
        same = not chosen or set(chosen) == IMPACT_DEFAULT_TYPES
        tail = "" if same else "~" + ".".join(chosen)
        code = "d" if direction == "dependencies" else "i"
        return f"im~{'.'.join(token(e) for e in starts)}~{code}~{depth}{tail}"

    @staticmethod
    def paths(source: dict, target: dict) -> str:
        return f"pa~{token(source)}~{token(target)}"

    @staticmethod
    def folder(folder_ref: str) -> str:
        return "fo~" + folder_ref

    @staticmethod
    def element_type(element_type: str) -> str:
        return "ty~" + element_type

    @staticmethod
    def layer(layer: str) -> str | None:
        key = LAYER_KEYS.get(layer)
        return "la~" + key if key else None
