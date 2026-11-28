"""
1.15.0 (API 3.24.0): recipe scripts, which make the recipes of many diagrams at once.

  check_recipe_script   what a script would make, or its errors by line; changes nothing (always offered)
  run_recipe_script     makes and updates the recipes (a write tool: offered when writing is on)

1.16.0 (API 3.25.0): every run keeps the script's text with the model, and a single recipe is edited as the script
of one diagram.

  recipe_scripts        the kept scripts of a model, or the text of one (always offered)
  check_recipe_script   with `view`: the script of that one recipe, and what saving it would change
  save_recipe_script    writes the script of one recipe into it (a write tool)

get_view gives a recipe's script (views.py).

1.17.0 (API 3.26.0): a script kept without running it, as a live template (its diagrams worked out from the model
whenever they are asked for; no views).

  keep_recipe_script    keeps a script as a live template, or to run later (a write tool)
  recipe_scripts        also says which are live, and gives a live template's diagrams as they are now

images.py's recipe_images saves an image of each diagram of a script, a kept script or chosen recipes.

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
from app.tools import READ_ONLY, Context, Limit, ModelRef, Ref, compact, page

SCRIPTS_NEED = "3.24.0"
EDIT_NEED = "3.25.0"
LIVE_NEED = "3.26.0"
LANGUAGE = "https://github.com/rnovicky/ArchiMateAPI/blob/main/RECIPE_SCRIPTS.md"
# Makes and updates recipes (created views); with delete_obsolete it also deletes some
RUN = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)
# Rewrites one recipe (1.16.0)
SAVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)
# Keeps (or replaces) a script's text (1.17.0)
KEEP = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

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

One recipe (get_view gives a recipe's script; check_recipe_script and save_recipe_script take `view`) is a
diagram block alone, without script and for each:

    diagram "ERP landscape"
      neighbourhood of "ERP" depth 2
      layout readable

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

    def needs_newer(e: ApiError, version: str = SCRIPTS_NEED, what: str = "Recipe scripts") -> ToolError | None:
        """The model (and view) was found before the call: 404/405 means an API without the endpoint."""
        if e.status in (404, 405) and "recipe script" not in str(e).lower():
            return ToolError(f"{what} need ArchiMate API {version} or later; api_status shows the version in use.")
        return None

    def edit_newer(e: ApiError) -> ToolError | None:
        return needs_newer(e, EDIT_NEED, "Recipes edited as scripts and kept scripts")

    async def recipe_of(m: dict, view: Any) -> tuple[dict, dict]:
        """A recipe and its script (GET …/views/{id}/recipe-script)."""
        v = await lookup.view(m["id"], view)
        if v.get("recipe") is None:
            raise ToolError(f"View \"{v.get('name')}\" ({v['id']}) is not a recipe; only a recipe is edited as a script.")
        try:
            return v, await api.get(f"/models/{m['id']}/views/{v['id']}/recipe-script")
        except ApiError as e:
            raise (edit_newer(e) or e) from e

    def one_recipe(m: dict, v: dict, report: dict, script_of: dict) -> dict[str, Any]:
        answer: dict[str, Any] = {"model": {"id": m["id"], "name": m["name"]},
                                  "view": {"id": v["id"], "name": v.get("name"), "version": v.get("version")},
                                  "ok": report.get("ok", False)}
        for key in ("errors", "warnings", "recipe", "changes", "changed", "detached", "revision"):
            if report.get(key) not in (None, []) or key == "changes" and "changes" in report:
                answer[key] = report[key]
        if script_of.get("gaps"):
            answer["gaps"] = script_of["gaps"]
        by = script_of.get("madeBy")
        if not answer["ok"]:
            answer["next"] = "Fix the errors (each names its line) and check again; nothing was saved."
        elif "changed" not in report:
            if by:
                answer["madeBy"] = by
                answer["next"] = (f"The recipe was made by the recipe script \"{by['script']}\", whose next run sets it "
                                  "back: change that script instead (recipe_scripts gives its text), or save with "
                                  "detach=true after asking the user.")
            elif report.get("changes"):
                answer["next"] = ("Show the user what would change and ask before saving it with save_recipe_script."
                                  if ctx.writable else "Saving needs writing, which is off on this server: the user can "
                                  "save it in the ArchiMate Browser (Edit as script… on the recipe).")
            else:
                answer["next"] = "The recipe says this already: nothing to save."
        return answer

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
            if report.get("storedScriptId") is not None:
                answer["storedScriptId"] = report["storedScriptId"]  # 1.16.0 (API 3.25.0): the run kept the text
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
        "With `view` (a recipe; API 3.25.0) it checks the script of that one recipe instead, a diagram block alone, "
        "and says what saving it with save_recipe_script would change (name, documentation, recipe).\n"
        + CHEAT_SHEET))
    @compact
    async def check_recipe_script(
        script: Script,
        model: ModelRef = None,
        view: Annotated[Ref | None, Field(description=(
            "A recipe (id, XMI identifier or name): check the script of this one recipe (get_view gives it) "
            "instead of a whole script."))] = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        m = await lookup.model(model)
        if view is not None:
            v, script_of = await recipe_of(m, view)
            try:
                report = await api.post(f"/models/{m['id']}/views/{v['id']}/recipe-script/check",
                                        {"script": script, "keepDocumentation": not script_of.get("documentationInScript")})
            except ApiError as e:
                raise (edit_newer(e) or e) from e
            return one_recipe(m, v, report, script_of)
        try:
            report = await api.post(f"/models/{m['id']}/recipe-scripts/check", {"script": script})
        except ApiError as e:
            raise (needs_newer(e) or e) from e
        return await shaped(m, report, limit)

    @server.tool(annotations=READ_ONLY)
    @compact
    async def recipe_scripts(
        model: ModelRef = None,
        name: Annotated[Ref | None, Field(description=(
            "A script's name (or id): its text as last run. Left out: the list of the model's scripts."))] = None,
    ) -> dict[str, Any]:
        """The recipe scripts of a model (API 3.25.0): every run keeps the script's text with the model. Without
        `name`, the list: each script's name, how many recipes it made, whether its text is kept (a script last run
        before API 3.25.0 has recipes but no text) and whether it is a live template (API 3.26.0: it makes no
        views; its diagrams are worked out from the model whenever asked for). With `name`, the text of one, to
        change it and check and run it again (check_recipe_script, run_recipe_script); for a live template also its
        diagrams as the model is now, each with a link (recipe_images saves their images)."""
        m = await lookup.model(model)
        try:
            listed = await api.get(f"/models/{m['id']}/recipe-scripts")
        except ApiError as e:
            raise (edit_newer(e) or e) from e
        if name is None:
            return {"model": {"id": m["id"], "name": m["name"]},
                    "scripts": [{k: x.get(k) for k in ("id", "name", "recipes", "stored", "live", "updatedBy",
                                                       "updatedAt") if k in x} for x in listed]}
        wanted = str(name).strip()
        found = [x for x in listed if x["name"] == wanted] or [x for x in listed if x["name"].casefold() == wanted.casefold()] \
            or [x for x in listed if str(x.get("id")) == wanted]
        if not found:
            names = ", ".join(f'"{x["name"]}"' for x in listed) or "none"
            raise ToolError(f"The model has no recipe script \"{wanted}\"; its scripts: {names}.")
        x = found[0]
        if not x["stored"]:
            raise ToolError(f"The text of the recipe script \"{x['name']}\" is not kept (it last ran before ArchiMate API "
                            f"3.25.0); its {x['recipes']} recipe(s) are there. Ask the user for the script, or write it anew.")
        script = await api.get(f"/models/{m['id']}/recipe-scripts/{x['id']}")
        answer = {"model": {"id": m["id"], "name": m["name"]},
                  **{k: script.get(k) for k in ("id", "name", "recipes", "live", "updatedBy", "updatedAt", "text") if k in script}}
        if script.get("live"):
            expanded = await api.get(f"/models/{m['id']}/recipe-scripts/{x['id']}/recipes")
            if expanded.get("errors"):
                answer["errors"] = expanded["errors"]
                answer["next"] = "The model no longer fits the template: fix the script and keep it again."
            token = model_token(m, await lookup.models()) if ctx.links else None
            answer["diagrams"] = [{"name": r["name"], "recipe": r["recipe"],
                                   **({"for": {"type": r["element"]["type"], "name": r["element"].get("name")}}
                                      if r.get("element") else {}),
                                   **({"browserLink": ctx.links.recipe_url(token, r["recipe"])} if token else {})}
                                  for r in expanded.get("recipes", [])]
        return answer

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

    @server.tool(annotations=SAVE)
    @compact
    async def save_recipe_script(
        view: Annotated[Ref, Field(description="The recipe: id, XMI identifier or name.")],
        script: Script,
        model: ModelRef = None,
        detach: Annotated[bool, Field(description=(
            "A recipe made by a recipe script: save it all the same and take it from that script, whose runs then "
            "leave it alone. Ask the user first; changing the script is usually the better way."))] = False,
        expected_version: Annotated[str | None, Field(description=(
            "The recipe's `version` as get_view gave it when you showed it to the user; refused if someone changed it "
            "since."))] = None,
    ) -> dict[str, Any]:
        """Save the script of one recipe into it (API 3.25.0): its name, documentation and what it draws, from a
        diagram block alone (get_view gives the recipe's script; check it with check_recipe_script and `view`
        first, show the user what would change and ask). The recipe keeps its id and its links. What the script
        leaves out (get_view lists it as gaps) is left out of the recipe. A script with errors changes nothing."""
        m = await lookup.model(model)
        v, script_of = await recipe_of(m, view)
        body = {"script": script, "keepDocumentation": not script_of.get("documentationInScript"), "detach": detach,
                "expectedVersion": expected_version or v.get("version")}
        try:
            report = await api.put(f"/models/{m['id']}/views/{v['id']}/recipe-script", body)
        except ApiError as e:
            err = e.body if isinstance(e.body, dict) else {}
            if err.get("code") == "SCRIPT_ERRORS" and isinstance(err.get("details"), dict):
                return one_recipe(m, v, {**err["details"], "changed": False}, script_of)
            if err.get("code") == "MADE_BY_SCRIPT":
                raise ToolError(f"{e} Nothing was changed. recipe_scripts gives the script's text; or, if the user "
                                "agrees, call again with detach=true.") from e
            if err.get("code") == "PRECONDITION_FAILED":
                raise ToolError(f"{e} Nothing was changed. Read it again (get_view), tell the user what changed, and "
                                "ask before saving again with the new version.") from e
            raise (edit_newer(e) or e) from e
        if report.get("changed"):
            changes.record(ctx.settings, ctx.key_name, "save_recipe_script", m,
                           {"kind": "view", "id": v["id"], "name": v.get("name")},
                           {"changes": report.get("changes"), "detached": report.get("detached")})
        return one_recipe(m, v, report, script_of)

    @server.tool(annotations=KEEP)
    @compact
    async def keep_recipe_script(
        script: Script,
        model: ModelRef = None,
        live: Annotated[bool, Field(description=(
            "true (default): a live template, which makes no views; the ArchiMate Browser lists its diagrams in the "
            "model tree, worked out from the model whenever it is opened. false: kept to run later."))] = True,
    ) -> dict[str, Any]:
        """Keep a recipe script with the model without running it (API 3.26.0): as a live template, or to run later
        with run_recipe_script. Check it first (check_recipe_script) and ask the user. A live template is always up to
        date: new elements that match appear, without a run. It may not share its name with a script that made
        recipes. Running a kept script makes its recipes and ends it being live."""
        m = await lookup.model(model)
        try:
            kept = await api.post(f"/models/{m['id']}/recipe-scripts", {"script": script, "live": live})
        except ApiError as e:
            err = e.body if isinstance(e.body, dict) else {}
            if err.get("code") == "SCRIPT_ERRORS" and isinstance(err.get("details"), dict):
                return {"model": {"id": m["id"], "name": m["name"]}, "ok": False, "errors": err["details"].get("errors"),
                        "next": "Fix the errors (each names its line) and keep it again; nothing was kept."}
            if err.get("code") == "SCRIPT_HAS_RECIPES":
                raise ToolError(f"{e} Nothing was kept.") from e
            raise (needs_newer(e, LIVE_NEED, "Live templates") or e) from e
        changes.record(ctx.settings, ctx.key_name, "keep_recipe_script", m, {"kind": "script", "name": kept.get("name")},
                       {"live": kept.get("live"), "diagrams": kept.get("diagrams")})
        return {"model": {"id": m["id"], "name": m["name"]}, "ok": True,
                **{k: kept.get(k) for k in ("id", "name", "live", "diagrams", "warnings") if kept.get(k) not in (None, [])},
                "next": ("Tell the user: the live template is under Views in the ArchiMate Browser's model tree."
                         if kept.get("live") else "Kept; run it with run_recipe_script when the user wants its recipes.")}
