"""
1.15.0 (API 3.24.0): recipe scripts, which make the recipes of many diagrams at once.

  check_recipe_script   what a script would make, or its errors by line; changes nothing (always offered)
  run_recipe_script     makes and updates the recipes (a write tool: offered when writing is on)

The API reads the script (POST …/recipe-scripts/check and …/run); the language is its RECIPE_SCRIPTS.md. The
answers are shaped for the assistant: every error with its line, each recipe with its status (new, changed,
unchanged) and, with BROWSER_URL, a link that opens it in the ArchiMate Browser (diagram_image draws such a link).
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from app import changes
from app.api_client import ApiError
from app.links import model_token
from app.tools import READ_ONLY, Context, Limit, ModelRef, compact, page

SCRIPTS_NEED = "3.24.0"
LANGUAGE = "https://github.com/rnovicky/ArchiMateAPI/blob/main/RECIPE_SCRIPTS.md"
# Makes and updates recipes (created views); with delete_obsolete it also deletes some
RUN = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)

Script = Annotated[str, Field(description="The text of the script (see the tool's description).", max_length=100_000)]

CHEAT_SHEET = """
A script (the ArchiMate API's RECIPE_SCRIPTS.md has it all):

    script "Service reviews"               # required; a later run updates the recipes this script made
    defaults                               # optional, before the first diagram: options for every diagram
      layout readable
      hide Junction
    for each BusinessService where @Status = "XY"      # one diagram per element; at most 50 unless "max N"
      diagram "Service: {name}"                        # {name} {type} {@Prop} {@Prop or 'n/a'}
        neighbourhood depth 1
          incoming all
          outgoing Serving, Realization
        colour by @Lifecycle
    diagram "ERP landscape"
      neighbourhood of ApplicationComponent "ERP" depth 2

Indentation (spaces) makes the blocks; "# " starts a comment; names and values go in quotes; keywords and types
in any case; Junction means AndJunction and OrJunction.
What a diagram shows, exactly one line (inside for each it is about the current element unless "of"/"from"):
  neighbourhood [of …] [depth 0-3] [incoming|outgoing|both], or with lines under it
      "incoming all|<RelTypes>" / "outgoing all|<RelTypes>" (types followed at every step)
  impact | dependencies [of …] [depth 1-10] [via <RelTypes>]
  elements …   paths [from …] to …   all <ElementType>   layer <strategy|business|application|technology|physical|
  motivation|implementation|other>   folder "Top/Sub"   relationships <RelType>   whole model
Elements: "Name", Type "Name" (when names repeat), #xmi-identifier, it, or "all <selection>" alone.
Selection: element | Type[, Type] [in folder "A/B"] [in layer x] [where <condition>] [max N]
Conditions: @P (set), not @P, @P = "v", @P != "v" (also when not set), @P contains "v", name = | != | contains "…",
  type = T, in folder "A/B", in layer x; and, or, not, brackets. Comparisons ignore case.
Options (diagram or defaults): hide <ElementTypes, RelTypes, layer x, or "RelType|any from Type|any to Type|any">;
  show only …; viewpoint "Application Cooperation"; only where @P [= | != | contains "v"]; label @P; colour by @P;
  language cs; nesting off|on|on with assignment|groupings|groupings with assignment; layout compact|balanced|
  readable; lines orthogonal|polyline|splines; bundle on|off; spacing 0.4-2.5; effort 1-50; documentation "…".
"""


def register(server: MCPServer, ctx: Context) -> None:
    api, lookup = ctx.api, ctx.lookup

    def needs_newer(e: ApiError) -> ToolError | None:
        """The model was found before the call: 404/405 means an API without the endpoint."""
        if e.status in (404, 405):
            return ToolError(f"Recipe scripts need ArchiMate API {SCRIPTS_NEED} or later; api_status shows the version "
                             "in use.")
        return None

    async def shaped(m: dict, report: dict, limit: int | None, *, ran: bool = False) -> dict[str, Any]:
        token = model_token(m, await lookup.models()) if ctx.links else None

        def link(recipe: str) -> dict[str, str]:
            url = ctx.links.recipe_url(token, recipe) if token else None
            return {"browserLink": url} if url else {}

        recipes = []
        for r in report.get("recipes", []):
            item: dict[str, Any] = {"name": r["name"], "status": r["status"]}
            if r.get("changes"):
                item["changes"] = r["changes"]
            if r.get("element"):
                e = r["element"]
                item["for"] = {"id": e["id"], "type": e["type"], "name": e.get("name")}
            if r.get("viewId"):
                item["viewId"] = r["viewId"]
            if r.get("documentation"):
                item["documentation"] = r["documentation"]
            item["recipe"] = r["recipe"]
            item.update(link(r["recipe"]))
            recipes.append(item)
        n = ctx.limit(limit)
        answer: dict[str, Any] = {
            "model": {"id": m["id"], "name": m["name"]},
            "script": report.get("script"),
            "ok": report.get("ok", False),
        }
        if report.get("errors"):
            answer["errors"] = report["errors"]
        if report.get("warnings"):
            answer["warnings"] = report["warnings"]
        if report.get("counts"):
            answer["counts"] = report["counts"]
        if recipes:
            answer["recipes"] = page(recipes[:n], len(recipes))
        if report.get("obsolete"):
            answer["obsolete"] = report["obsolete"]
        if ran:
            answer["changed"] = report.get("changed", False)
            if report.get("revision") is not None:
                answer["revision"] = report["revision"]
        if not answer["ok"]:
            answer["next"] = "Fix the errors (each names its line) and check the script again; nothing was made."
        elif not ran:
            todo = report["counts"]["new"] + report["counts"]["changed"]
            answer["next"] = (("Show the user what it would make and ask before running it with run_recipe_script."
                               if ctx.writable else "Running it needs writing, which is off on this server: the user "
                               "can run it in the ArchiMate Browser (Recipe script… in the model's menu).")
                              if todo or report["counts"]["obsolete"] else "Nothing to do: the recipes are up to date.")
        return answer

    @server.tool(annotations=READ_ONLY, description=(
        "Check a recipe script: what it would make in a model, without changing anything. A recipe is a stored "
        "diagram that the ArchiMate Browser draws afresh from the model whenever it is opened; a script makes many "
        "at once, e.g. one for each business service with a property. The answer lists every error with its line "
        "and a suggestion (fix them and check again), or each recipe the script would make: new, changed (and what) "
        "or unchanged compared with what an earlier run of the same script made, and the obsolete ones that run "
        "made and the script no longer makes. Check before run_recipe_script, and show the user the result.\n"
        + CHEAT_SHEET))
    @compact
    async def check_recipe_script(script: Script, model: ModelRef = None, limit: Limit = None) -> dict[str, Any]:
        m = await lookup.model(model)
        try:
            report = await api.post(f"/models/{m['id']}/recipe-scripts/check", {"script": script})
        except ApiError as e:
            raise (needs_newer(e) or e) from e
        return await shaped(m, report, limit)

    if not ctx.writable:
        return

    @server.tool(annotations=RUN)
    @compact
    async def run_recipe_script(
        script: Script,
        model: ModelRef = None,
        delete_obsolete: Annotated[bool, Field(description=(
            "Also delete the recipes an earlier run of this script made that it no longer makes (check lists them as "
            "obsolete). Ask the user first: it cannot be undone."))] = False,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """Run a recipe script: make its new recipes and update its changed ones (and with delete_obsolete delete its
        obsolete ones), in one change. Check it with check_recipe_script first, show the user what it would make
        and ask. Running a script again updates the recipes it made rather than making them twice. A script with
        errors changes nothing: the answer lists them as check_recipe_script does."""
        m = await lookup.model(model)
        try:
            report = await api.post(f"/models/{m['id']}/recipe-scripts/run",
                                    {"script": script, "deleteObsolete": delete_obsolete})
        except ApiError as e:
            body = e.body if isinstance(e.body, dict) else {}
            if body.get("code") == "SCRIPT_ERRORS" and isinstance(body.get("details"), dict):
                return await shaped(m, {**body["details"], "changed": False}, limit, ran=True)
            raise (needs_newer(e) or e) from e
        deleted = [o for o in report.get("obsolete", []) if o.get("deleted")]
        if report.get("changed"):
            changes.record(ctx.settings, ctx.key_name, "run_recipe_script", m,
                           {"kind": "script", "name": report.get("script")},
                           {"counts": report.get("counts"), "deleted": [o["name"] for o in deleted]})
        return await shaped(m, report, limit, ran=True)
