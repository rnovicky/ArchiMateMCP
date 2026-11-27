# Changelog

## 1.16.0 (2026-11-27)

For the ArchiMate API 3.25.0; the rest works with the API as before.

* **`get_view` on a recipe** also gives it as the script of one diagram
  (`script`), what a script cannot say (`scriptGaps`) and, for a recipe made
  by a recipe script, that script and the line of the diagram (`madeBy`).
* **`check_recipe_script` with `view`** checks the changed script of one
  recipe and says what saving it would change (name, documentation, recipe).
* **`save_recipe_script`** (writing on) saves it into the recipe, which keeps
  its id and links. A recipe made by a recipe script is refused, since its
  next run would set it back, unless `detach` (ask the user first). Every
  save that changes something is recorded in the change log.
* **`recipe_scripts`** lists the scripts kept with a model (every run keeps
  its text since API 3.25.0) and gives the text of one, so that Claude can
  change a script written elsewhere and run it again. `run_recipe_script`
  answers its `storedScriptId`.
* The server's instructions and the language in short in
  `check_recipe_script` mention the script of one recipe.

## 1.15.0 (2026-11-27)

For the ArchiMate API 3.24.0; the rest works with the API as before.

* **Recipe scripts:** a recipe script makes the recipes of many diagrams at
  once, e.g. *one for each business service with Status XY*. The language is
  described in the API's RECIPE_SCRIPTS.md.
  * **`check_recipe_script`** is always offered and reads only. It says what a
    script would make, without changing anything. Errors come back with their
    line and a suggestion. Otherwise each recipe comes back with its status
    (new, changed and what, unchanged, obsolete), the element it was made for,
    its recipe and, with `BROWSER_URL`, a `browserLink` (which
    `diagram_image` can draw). The tool's description holds the language in
    short, so that the assistant can write scripts.
  * **`run_recipe_script`** is offered when writing is on. It makes and
    updates the recipes; `delete_obsolete` also deletes the ones the script no
    longer makes. A script with errors changes nothing and is answered like a
    check. Every run that changes something is recorded in the change log.
  * The server's instructions say to check first and to show the user the
    result before running.
* **`neighbourhood`:** `incoming_types` and `outgoing_types` follow only
  those relationship types in that direction, at every step, e.g. every
  incoming relationship but outgoing only Serving and Realization. Its
  `browserLink` keeps them (Browser 2.33.0).

## 1.14.1 (2026-11-27)

No change to the server itself.

* **Install package:** links in its Markdown files to files it leaves out
  (`PLAN.md`, `IMPROVEMENTS.md`, the API's `ACCESS_RIGHTS.md` and
  `EPIC_MULTIUSER.md`) now point to the same file on GitHub
  (`createinstallpackage.ps1`).

## 1.14.0 (2026-11-20)

* **`update_view` and `delete_view`** also rename and delete views of the
  model's source, on a model mastered here (ArchiMate API 3.23.0). The API
  decides: on a model linked to a file, or with an older API, the refusal
  says what to do instead. The server's instructions and the tools'
  descriptions say so; what a source view shows is still never changed.

## 1.13.0 (2026-11-20)

Recipes (ArchiMate API 3.22.0, Browser 2.30.0): created views that hold how a
generated diagram is made (its Browser link) instead of a drawing.

* **`list_views`** gives a recipe's `recipe`.
* **`get_view`** of a recipe says what it is (no drawing, no elements of its
  own), with its recipe and, with `BROWSER_URL`, the link that draws it.
* **`update_view`, `delete_view`** rename and delete recipes as other created
  views; **`diagram_image`** with a recipe draws its diagram.

## 1.12.0 (2026-11-09)

Images of diagrams for reports and documents (MCP-35). Needs the ArchiMate
Browser 2.29.0 (its render mode) next to this server or in `BROWSER_DIR`, and
Chrome or Edge; works with the ArchiMate API as before (3.12.0 or later).

* **`diagram_image`:** saves a diagram as a PNG or SVG file in `IMAGE_DIR`
  (default `images` in the server's folder), drawn exactly as the Browser
  draws it: a view as it is stored, chosen elements, or the diagram of a
  `browserLink` of another answer (a neighbourhood, an impact analysis, paths,
  a proposed view) with the Browser's rules. Options: `format` (png, svg,
  both), `direction` and `nesting` of a generated diagram, the PNG's `scale`,
  the `file` name, and a small `preview` for the assistant. The answer names
  the files with their sizes.
* **How it draws (`app/render.py`):** the first image starts a Browser
  server of the MCP server's own on a free port of 127.0.0.1 and Chrome or
  Edge without a window (Playwright, with the installed browser); both stop
  after `RENDER_IDLE` seconds without an image, and with the MCP server. The
  Browser server holds no key: the page sends the tool's key (with
  `CLIENT_KEYS` the client's) in a header.
* **New settings:** `BROWSER_DIR`, `IMAGE_DIR`, `RENDER_BROWSER`,
  `RENDER_TIMEOUT`, `RENDER_IDLE` (`.env.example`).
* **New requirement:** the Python package `playwright` (`requirements.txt`);
  it downloads no browser of its own.
* `diagram_image` writes files, so it is not marked read-only; it changes no
  model and is offered with a reader key. The instructions for the assistant
  mention it for reports.
* **Every write sends a version** (for an API with `REQUIRE_IF_MATCH=true`,
  which refuses a change of an existing item that says none, `428`): the
  version the assistant gives (`expected_version`), or else the one the tool
  reads just before writing. Before, `file_item`, `delete_folder`, the
  model's own properties (`set_property` with `kind=model`) and the changes of
  `apply_changes` without `expected_version` sent none, and failed there.
  * `file_item` and `delete_folder` (with `move_contents_to`) are now one
    operation of the API's changes endpoint each: one transaction, checked
    against the item's or folder's version. A stale `expected_version` of
    `delete_folder` is refused by the API, which says who changed it.
  * `apply_changes` reads the version of each existing item a change without
    `expected_version` touches, once per item, unless `expected_revision`
    covers the model.
  * What a version read in the same call guards against: only a change made
    between that read and the write. A change made since the assistant
    showed the item to the user is caught only with `expected_version`; the
    instructions for the assistant say so.
* **`api_status`** shows `requireIfMatch`, from the API's `GET /auth/me`
  (API 3.21.0; `null` from an older API).
* **Tests:** the test API runs with `REQUIRE_IF_MATCH=true` (not taken from
  the API's own `.env`), so the whole suite shows that every write tool
  sends a version; the tests' own writes, which stand for someone else, send
  `If-Match: *`. `ARCHIMATE_TEST_REQUIRE_IF_MATCH=false` runs the suite
  against an API that does not ask. `tests/test_strict.py` calls every write
  tool without `expected_version` against an API that requires a version, in
  either case.

## 1.11.0 (2026-10-30)

Resources that announce their change (MU-15; the API's
`EPIC_STAGE3_DECISIONS.md`, U10). Uses the change events of the ArchiMate
API 3.17.0; with an older API it works as before.

* **Subscriptions:** a client may subscribe to the resources, with
  `subscriptions/listen` (protocol 2026-07-28) or `resources/subscribe` and
  `resources/unsubscribe` (earlier versions; the server now declares
  `resources.subscribe`).
* While any client subscribes, the server listens to the API's change
  events on one stream and notifies: `archimate://models` on a change of
  any model; an element or a view on any change of its model; the
  metamodel never. The notification means "read it again".
* Nobody subscribed: no stream. The tools are unchanged; they read fresh
  on every call.

## 1.10.0 (2026-10-30)

Where a model is mastered (the API's `BROWSER_EDITING.md`, BL-58). Works with
the API 3.12.0 as before; `editedSinceImport` needs 3.16.0, and with an older
API `master` is told from the link alone.

* **`master` in `list_models` and `model_overview`:** `file` for a model
  linked to a file (updated from it, read-only here; `model_overview` now
  also names the file as `linkedTo`), `api` for a model kept here. A model
  kept here also says `editedSinceImport`: the changes made since its last
  import, which a replace from a file would undo.
* **A refusal on a linked model says what to do instead:** make the change
  in Archi and save the file, or unlink the model to edit it here; a new
  view can still be proposed with `propose_view`. The server's instructions
  tell the assistant not to write to a model mastered by its file.

## 1.9.0 (2026-10-29)

Views (MCP-28, decision D22): the layout of a view stays with the ArchiMate
Browser. Needs the ArchiMate API 3.15.0 for created views (with an older one
every view counts as a view of the source) and the Browser 2.22.1 for the
name in a proposed view's link.

* **`propose_view`** (a read tool): the elements, optionally the
  relationships, and a name become a link that opens them as a diagram in
  the ArchiMate Browser with *Save as view…* and the name filled in. Nothing
  is stored; the user arranges the diagram and saves it there. Needs
  `BROWSER_URL`.
* **Where a view comes from:** `list_views` and `get_view` answer `origin`
  (`source` or `created`); a created view also who made it, when, which
  view it copies (`basedOn`) and what an update from the source took out of
  it (`lost`). `list_views` filters by `origin`.
* **`update_view`** (name, documentation) and **`delete_view`** (asks
  first) for created views, and `updateView` and `deleteView` in
  `apply_changes`. A view of the model's source is refused, with a hint to
  `propose_view`.

## 1.8.0 (2026-10-26)

Needs the ArchiMate API 3.12.0. Stage 2 of the multi-user epic, "safe
concurrent writes" (the API's `EPIC_STAGE2_DECISIONS.md`, T6), the MCP
server's part.

* **Versions in the answers:** `get_element`, `get_relationship`,
  `get_view` and `browse_folders` (a folder) answer the item's `version`.
* **`expected_version`** on `update_element`, `delete_element`,
  `update_relationship`, `delete_relationship`, `set_property`,
  `remove_property` (the version of the element, relationship or view),
  `update_folder`, `delete_folder`, and on every change of `apply_changes`.
  The assistant passes the version of what it showed the user; when someone
  changed the item since, nothing is changed. Without it, a tool sends the
  version it read in the same call, so nobody's change slips in between.
  `update_model` and the property-definition tools always send the version
  they read.
* **A refused write explains itself:** the assistant is told who changed
  the item, when, with which client, and which fields from what to what,
  and is asked to read it again, tell the user and ask before writing again
  (also in the server's instructions). D15 ("the last write wins") no
  longer holds.
* `set_property` and `remove_property` on an element, relationship or view
  go through the API's changes endpoint, which checks the owner's version
  in the same transaction.

## 1.7.1 (2026-10-26)

* `model_history` asks for the history of an element, relationship or view
  by its XMI identifier, which stays across a replace of the model; an id is
  given anew by a replace and may be given again after a deletion.

## 1.7.0 (2026-10-26)

Needs the ArchiMate API 3.11.0. Stage 1 of the multi-user epic, "who and
when" (the API's `EPIC_STAGE1_DECISIONS.md`, S9, S10, S12, S14), the MCP
server's part.

* **Each HTTP client with its own key** (MU-2): with `CLIENT_KEYS=true` a
  client sends its own key of the ArchiMate API as `Authorization: Bearer
  <key>` instead of a shared `MCP_TOKEN`. The server asks the API whose key
  it is and serves that client with that key: the API and its record of
  changes see the person, and the write tools follow their role (with
  `ALLOW_WRITE`). A key the API refuses gets `401`. `API_KEY` may stay
  empty. Over stdio nothing changes: the key in `.env` is the person's own.
  `MCP_TOKEN` stays, for a server that every client uses with its key;
  the two are not set together.
* **`model_history`**: who changed what in a model, and when, from the API's
  record of changes (`GET /models/{id}/history`): for one element,
  relationship or view, one user, a time span; with the client, the
  operation, and the fields before and after. Offered with a key that may
  write, as the API gives the record to editors.
* **`X-Client: ArchiMate MCP 1.7.0`** on every request, so that the API's
  record tells this server's changes from the Browser's and scripts'.
* **`changes.log` is off by default** (`CHANGE_LOG` empty): the API's record
  is the one that counts. Set `CHANGE_LOG=changes.log` to keep the server's
  own record of its tool calls, as before.
* `api_status` also gives the key's label and whether clients send their own
  keys.

## 1.6.0 (2026-10-25)

Needs the ArchiMate API 3.10.0.

* **Folders in `apply_changes`** (MCP-25, on the API's BL-52): the changes
  `createFolder`, `updateFolder` and `deleteFolder`, in the same
  transaction as the rest. A folder made by one change takes later items
  as `"folder": "@ref"`, and is the `parent` of later folders.
* **The model itself** (MCP-26): `set_property` and `remove_property` with
  `kind=model` for the model's own properties (editor); `update_model` for
  its name, documentation and version label, offered only with a key that
  may change models (the API's role `admin`, like `create_model`).
* **Property definitions** (MCP-27): `update_property_definition` renames
  a property or changes its data type for all its values at once;
  `delete_property_definition` deletes one, and one that still has values
  only with `with_values=true`.
* **Asking before deleting**, after the real-use tests (C7b, C8): the
  descriptions of the delete tools, their refusals and the server's
  instructions tell the assistant to tell the user what would go and to
  ask, and not to choose where a folder's contents go. An assistant that
  had deleted an element with `cascade=true` at once, and chosen a folder
  for the contents of a deleted folder itself, should now ask. Whether the
  client asks for permission before a destructive tool is the client's
  setting; the delete tools are marked destructive.
* `set_property` and `remove_property` take `name` and `value` first;
  `item` is optional (not needed for `kind=model`).

## 1.5.0 (2026-10-25)

Needs the ArchiMate API 3.9.0, as 1.4.0.

* **Folders** (MCP-24): `create_folder` (in a folder or at the top level),
  `update_folder` (rename, documentation, move with everything in it) and
  `delete_folder`. Two folders of one name side by side are refused, since
  a path would no longer say which is meant; a folder does not move into
  itself. `delete_folder` deletes only an empty folder, unless
  `move_contents_to` names where its sub-folders and items go: elements,
  relationships and views are never deleted with a folder. Every change is
  a line in the record of changes. The API had the endpoints; the first
  real use missed them (step C7 of the real-use tests).
* Not yet in `apply_changes`: the API's changes in one transaction have no
  folder operations (BL-52, MCP-25).

## 1.4.0 (2026-10-25)

Needs the ArchiMate API 3.9.0.

* **`apply_changes`** (MCP-22): many changes to a model in one call and one
  transaction, all or nothing: create, update and delete elements and
  relationships, set and remove properties, file items. A change names an
  item created by an earlier one as `@ref`; existing items by id, XMI
  identifier or name. New items go into the folder of their layer, as with
  the single tools. The first change that fails undoes all of them and is
  named in the error; `expected_revision` applies the changes only to the
  model as it was read. Every change is a line in the record of changes.
  Asked for after the first real use: a clean-up of 27 relationships took
  27 calls.
* **`create_model`** (MCP-23): a new, empty model, by default with the
  top-level folders Archi gives a new model, so that new elements are filed
  by their layer at once. Offered only with a key that may create models
  (the API's role `admin`).
* The server's description tells the assistant to use `apply_changes` for
  more than two or three changes.

## 1.3.0 (2026-10-24)

Writing (MCP-15, decisions D11 to D21 of PLAN.md). Needs the ArchiMate API
3.7.0, as before.

* **Nine write tools**, offered only with `ALLOW_WRITE=true` and a key with
  the role `editor` (otherwise the server reads, as before):
  `create_element`, `update_element`, `delete_element`,
  `create_relationship`, `update_relationship`, `delete_relationship`,
  `set_property`, `remove_property`, `file_item`.
* A new item gets an XMI identifier like Archi's and is filed in the
  top-level folder of its layer ("Relations" for relationships) unless the
  call names a folder. A likely duplicate (same type and name, or the same
  relationship between the same ends) is a warning.
* Deletes are marked destructive, so clients ask first; an element with
  relationships or in views is deleted only with `cascade=true`, and the
  answer lists what went with it.
* The API's rules apply (`RELATIONSHIP_RULES`, roles, linked models); a
  refusal reaches the assistant with what would be allowed.
* Every write is recorded, one JSON line each, in `changes.log` (setting
  `CHANGE_LOG`) and in the server's log; every answer gives the model's new
  revision. `api_status` says whether the server may write.

## 1.2.0 (2026-10-24)

Which relationships ArchiMate allows. Needs the ArchiMate API 3.7.0.

* **`allowed_relationships`** (MCP-21): the relationship types ArchiMate 3.2
  allows from one concept to another (the table Archi uses), for one pair,
  or for every concept on one side. For choosing a relationship and for
  judging one found in a model.
* **`model_quality`** has the API's new check `relationshipsNotAllowed`:
  relationships whose type is not allowed between the types of their ends.
  The prompt `model_quality_review` weighs them.

## 1.1.0 (2026-10-24)

The API's reports. Needs the ArchiMate API 3.6.0.

* **`model_quality`** (MCP-18): elements in no view or without
  relationships, unfiled items, duplicate names within a type, empty views,
  empty labels; per check the total and the first items.
* **`relationship_matrix`** (MCP-19): which elements of one set connect to
  which of another, directly or along a path pattern of up to three steps;
  each pair with its count and its paths as readable chains.
* **`landscape`** (MCP-20): the elements below root elements along nesting
  relationships, as a tree, with property values and the values found.
* The prompt `model_quality_review` starts from `model_quality`.

## 1.0.0 (2026-10-23)

Phase 5 of PLAN.md: the release. Needs the ArchiMate API 3.4.0.

* `deploy.ps1` reads the browser's version from `js/version.js` and takes
  any version number as newer than an installation that has only a date
  (the browser before 2.7.0); the script is the same in all three packages.
* **Ids as numbers:** every parameter that names a model, element,
  relationship, view or folder takes a number as well as text. Claude Code
  sends ids as numbers, which the tools refused (found by trying the server
  in Claude Code).
* **A warning at start** when the API key may do more than read; the server
  only reads and should get a key with the role `reader`.
* **The API's error messages reach the assistant as text.** The client read
  FastAPI's `detail`, but the API answers `{code, message, details,
  candidates}`, so errors arrived as a raw dict. Now: the message, what is
  wrong with which parameter (422), and the candidates of a 409.
* `search` leaves out an empty `matchedIn` (a search by filters only).
* `requirements.txt` takes the MCP SDK below 3 (`mcp>=2.3.0,<3`): its API
  changes between major versions. `runtests.ps1` lints with `ruff` first.
* README: what to ask, the corrected notes on tests and development.

## 0.3.0 (2026-10-23)

Phase 2 of PLAN.md: analysis. Needs the ArchiMate API 3.4.0.

* **`impact_analysis`, `find_paths`, `neighbourhood`, `subgraph`**
  (MCP-8 to MCP-10): the API's graph helpers, with every element named and
  paths as readable chains.
* **Links to the ArchiMate Browser** (MCP-11, new setting `BROWSER_URL`):
  answers carry a `browserLink` that opens what they describe as a diagram;
  `browser_link` makes one on request. Items by XMI identifier, as the
  browser's own links.
* **Resources** (MCP-12): `archimate://metamodel` (from the API's new
  `GET /metamodel`), `archimate://models`, and a view or an element by id.
* **Prompts** (MCP-13): `impact_of_change`, `describe_view`,
  `model_quality_review`.

## 0.2.0 (2026-10-23)

Phase 1 of PLAN.md: the tools that read. Needs the ArchiMate API 3.3.0.

* **`list_models`, `model_overview`, `search`, `get_element`,
  `get_relationship`, `list_views`, `get_view`, `browse_folders`**
  (MCP-1 to MCP-7). All read-only.
* **Things by name:** models, elements and views may be given by id, XMI
  identifier or name, folders by path. A name that matches several things
  is refused with the candidates; it is never guessed.
* **Short answers:** lists stop at `MAX_RESULTS` (new setting, default
  100) and say so; views without coordinates; answers as compact JSON.
* **`DEFAULT_MODEL`** (new setting): the model the tools read when they are
  not told which.
* The tests import a second model (the API's basic model), so that the
  tools must be told which model to read.

## 0.1.0 (2026-10-23)

The frame (phase 0 of PLAN.md); no tools that read models yet.

* **The server** on the MCP Python SDK 2.x, over **stdio** (MCP clients
  start `run_server.py stdio`) and **streamable HTTP** at
  `http://HOST:PORT/mcp` (default port 8100).
* **Checks the ArchiMate API at start:** 3.2.0 or newer, `/api/v2`, and a
  key it takes. A wrong key or an old API stops the server; an API that
  does not answer yet only gives a warning.
* **HTTP behind the server's own token** (`MCP_TOKEN`, sent as
  `Authorization: Bearer`). Without one the server listens only on a
  loopback address. `GET /health` answers without it.
* **The tool `api_status`:** the API's URL and version, the key's name and
  role.
* **`archimatemcp.bat`** with `install`, `deploy`, `start`, `stdio`, `check`
  and `config` (prints the configuration for Claude Desktop and Claude
  Code); `createinstallpackage.ps1` and `deploy.ps1` as in the API and the
  browser.
* **Tests** against the real ArchiMate API, through the SDK's client:
  in-process, over stdio and over HTTP.
