# Plan: ArchiMate MCP server

ArchiMate MCP is the third tool next to the ArchiMate API and the ArchiMate
Browser. It is an MCP server ([Model Context Protocol](https://modelcontextprotocol.io))
that lets an AI assistant (Claude Desktop, Claude Code, other MCP clients)
read, and maybe change, the models that the ArchiMate API holds.

Like the browser, it is a client of the API and nothing else. It never reads
the database or the exchange files itself. When it needs something the API
cannot answer well, the API is extended (a BL item in the API's
`IMPROVEMENTS.md`), not worked around here.

* **Status as of 2026-11-28: 1.17.0**: recipe scripts (1.15.0), a recipe as a script and kept scripts
  (1.16.0), live templates and `recipe_images` (1.17.0). What is open is listed in
  [Open ideas and tasks](#open-ideas-and-tasks-as-of-2026-11-28).
* **Status as of 2026-11-20: 1.14.0**: `update_view` and `delete_view` also for views of the model's source on a
  model mastered here (API 3.23.0).
* **Status as of 2026-11-20: 1.13.0**: recipes (API 3.22.0, Browser 2.30.0): `list_views` and `get_view`
  say what a recipe is and give its recipe and link; `diagram_image` draws one.
* **Status as of 2026-11-09: 1.12.0**: images of diagrams (MCP-35): `diagram_image` saves a diagram
  as a PNG or SVG file for reports, drawn by the ArchiMate Browser 2.29.0 (render mode) in Chrome or Edge
  without a window, from a Browser server the MCP server starts for itself. Every write sends a
  version (the assistant's `expected_version`, or the one read just before), so an API with
  `REQUIRE_IF_MATCH=true` takes them; `file_item` and `delete_folder` are one operation of the changes
  endpoint; `api_status` shows `requireIfMatch` (API 3.21.0); the tests run against such an API.
* **Status as of 2026-10-30: 1.11.0**: resources that announce their change (MU-15), the MCP
  server's part of stage 3 of the multi-user epic, on the API's change events (3.17.0).
* **Status as of 2026-10-30: 1.10.0**: where a model is mastered (`master`, `editedSinceImport`;
  the API's BL-58, 3.16.0), and refusals on a linked model that say what to do instead.
  Parked, waiting for the user's decision: MCP-16 and MCP-29.
* **Status as of 2026-10-29: 1.9.0**: views (MCP-28, D22): `propose_view`, the origin of a view in
  `list_views` and `get_view`, `update_view` and `delete_view` for created views, on API 3.15.0 and
  Browser 2.22.1.
* **Status as of 2026-10-26: 1.8.0**: versions in the answers and
  `expected_version` in the write tools (MCP-32), the MCP server's part of
  stage 2 of the multi-user epic, on API 3.12.0.
* **Status as of 2026-10-26: 1.7.0**: each HTTP client with its own key and
  `model_history` (MCP-30, MCP-31), the MCP server's part of stage 1 of the
  multi-user epic, on API 3.11.0.
* **Status as of 2026-10-25: 1.6.0**: folders in `apply_changes`, the model's
  name and properties, property definitions (MCP-25 to MCP-27) on API 3.10.0;
  the delete tools ask first (real-use tests C7b, C8). Parked: MCP-16,
  MCP-28, MCP-29.
* **Status as of 2026-10-25: 1.5.0**: folders (MCP-24). What the API offers
  and this server does not yet is in MCP-16 and MCP-25 to MCP-29.
* **Status as of 2026-10-25: 1.4.0**: `apply_changes` and `create_model`
  (MCP-22, MCP-23) on API 3.9.0.
* **Status as of 2026-10-24: 1.3.0, with writing.** After 1.0.0 came the API's
  reports (1.1.0, MCP-18 to MCP-20), the allowed relationships (1.2.0,
  MCP-21) and writing for one writer at a time (1.3.0, MCP-15, decisions D11
  to D21); 81 tests. Left: MCP-16 (models as a whole) and what the
  multi-user epic of the API (`EPIC_MULTIUSER.md`) takes in.
* **Status as of 2026-10-23: 1.0.0 is released.** Phases 0, 1, 2 and 5
  are done (0.1.0 to 1.0.0): the scripts and documents, the API client, the
  server over stdio and HTTP (MCP-14 came with phase 0), the reading tools
  (MCP-1 to MCP-7), the graph tools, links to the ArchiMate Browser,
  resources and prompts (MCP-8 to MCP-13); 63 tests. The API grew twice for
  it: the folder tree without its items (BL-49, 3.3.0) and the metamodel
  (BL-50, 3.4.0). Tried in Claude Code against real models. Left: phase 4
  (writing, after 1.0.0 by D4), and the HTTP transport from a second
  machine (phase 3). The decisions at the end are taken (the
  recommendations, 2026-10-23).
* **API it is built on:** 3.7.0 or newer (since 1.2.0), `/api/v2` only.
* **SDK:** the MCP Python SDK 2.3 (`mcp`); its server class is `MCPServer`,
  FastMCP of the 1.x SDK.

## Open ideas and tasks (as of 2026-11-28)

What is unfinished or undecided for the MCP server. The shared ideas (the
reporting tool, PostgreSQL, the multi-user epic, the recipe scripts' open
items) are in the API's PLAN.md, section *Open ideas and tasks*. Remove an
entry when it is done or dropped.

* **Waiting for your decision:** MCP-16 (model tools: import, export, a dry
  run, refreshing a linked model) and MCP-29 (`delete_model`, the metadata
  blocks, the Browser's helper endpoints), parked since 2026-10-25.
* **Recipe scripts:** no tool forgets a kept script's text (API PLAN.md R4).
  `recipe_images` writes images and an `index.md`; a Word or PDF report from
  them is left to Claude, or to the reporting tool (API PLAN.md X1).
* **Real-use tests still to do** ([REAL_USE_TESTS.md](REAL_USE_TESTS.md),
  `../todo.txt`): part B (B1 to B8), C13 and C14, parts D and E, A9 (a report
  with diagram images), images of a large view, change notifications in a
  client that subscribes, and sending the findings back.

## How to track progress

The same rules as in the API and the browser:

* Change the **Status** column in the tracker: `todo`, `doing`, `done`,
  `dropped`, or `blocked` (with the reason in the Notes column).
* An item is `done` when it has automated tests, the suite passes, and the
  README and CHANGELOG say what it does.
* The commit subject names the item (`Add MCP-4: …`).

## What it is made of

The folder gets the same set of scripts and documents as its two siblings:

| File | Like | Purpose |
| --- | --- | --- |
| `README.md` | both | Quick start, configuration, the tools, client set-up, install package, development |
| `CHANGELOG.md` | API | One section per release (semantic versions, D9) |
| `PLAN.md` | both | This file |
| `IMPROVEMENTS.md` | both | Backlog after 1.0.0 (MCP-n items) |
| `.env.example` | both | Every setting, commented; a test checks that it names every setting |
| `.gitignore` | API | `.env`, `.venv`, caches, `dist/` |
| `requirements.txt`, `requirements-dev.txt` | API | Runtime and test packages |
| `pytest.ini` | API | |
| `archimatemcp.bat` | both | `install`, `deploy <folder> [start]`, `start` (HTTP), `stdio`, `check` (reaches the API with the key?), `config` (prints the client snippet for Claude Desktop / Claude Code) |
| `run_server.py` | – | Starts the server from any working directory: MCP clients start a stdio server without choosing one |
| `deploy.ps1` | both | Install or update from an unzipped package: refuses while the port answers, backup, MANIFEST copy, keeps `.env` and `.venv`, comments out unknown settings, pip install |
| `createinstallpackage.ps1` | both | `dist/ArchiMateMCP_<timestamp>.zip` with `MANIFEST.txt`; `-OutputDir`, `-NoZip`, `-KeepFolder` |
| `runtests.ps1` | API | Runs the suite (unit tests, then the tests against a real API) |
| `app/` | API | The server (package layout below) |
| `tests/` | both | Unit tests and tests against the sibling ArchiMate API |

Package layout (Python, D1); the files marked *later* come with the phases:

```
app/
  __main__.py      python -m app [stdio | http | check | config]; Ctrl+C ends it quietly
  config.py        pydantic-settings, unknown settings refused (as in the API)
  api_client.py    client of /api/v2: key, timeouts, version check, errors
  server.py        the MCPServer; tools registered here
  http.py          the HTTP transport behind MCP_TOKEN, GET /health
  version.py       APP_VERSION, MIN_API_VERSION
  tools/           later: models.py, search.py, elements.py, views.py, graph.py
  resources.py     later: archimate://... resources
  prompts.py       later: prompt templates
  format.py        later: compact answers, size limits
```

## How it talks to the API

* Every call goes to `API_URL` (default `http://127.0.0.1:8000`) with the key
  `API_KEY` in `X-API-Key`.
* At start it asks `/health` and `/api/v2/auth/me`: an API older than
  `MIN_API_VERSION` (3.6.0) or a key that does not work stops it with a
  clear message. The role of the key decides which tools are offered
  (a reader key gets no write tools, D4).
* API errors (404, 409 with candidates, 422) become MCP tool errors with the
  API's message, so the assistant can correct itself.

## The tools

Tools are shaped around questions an architect asks, not one per endpoint.
Each answer is short (names, types, ids) and says when it was cut
(`MAX_RESULTS`). Ids in answers are the API's ids; tools also accept XMI
identifiers and, where unambiguous, names (`/resolve`).

| ID | Tool | API it uses | Phase | Status |
| --- | --- | --- | --- | --- |
| MCP-1 | `list_models`: models with revision, counts, linked or not | `GET /models`, `/stats` | 1 | done |
| MCP-2 | `model_overview`: element/relationship/view counts by type and layer, property names | `/stats`, `/properties/index` | 1 | done |
| MCP-3 | `search`: elements, relationships, views by text, type, layer, property value | `/search`, `/elements`, `/relationships` | 1 | done |
| MCP-4 | `get_element`: documentation, properties, folder path, relationships in and out, views it is shown in | `/elements/{id}`, `/neighbours`, `/folders`, `/views` | 1 | done |
| MCP-5 | `get_relationship` | `/relationships/{id}`, `/views` | 1 | done |
| MCP-6 | `list_views`, `get_view`: a view as its elements and relationships (not coordinates), its notes, links to other views | `/views`, `/views/{id}/content`, `/links` | 1 | done |
| MCP-7 | `browse_folders`: the organization tree, one level at a time | `/organizations?foldersOnly` (BL-49), `/organizations/{id}/contents` | 1 | done |
| MCP-8 | `impact_analysis`: what depends on / is affected by an element, by level | `POST /graph/impact` | 2 | done |
| MCP-9 | `find_paths`: how two elements are connected | `GET /graph/paths` | 2 | done |
| MCP-10 | `neighbourhood`, `subgraph`: the elements around a set of elements, the relationships among them | `POST /graph/neighbourhood`, `/subgraph` | 2 | done |
| MCP-11 | `browser_link`: a link that opens a diagram of given elements, or a view, in the ArchiMate Browser (D7) | none (link format of the browser) | 2 | done |
| MCP-12 | Resources: `archimate://models`, `archimate://models/{id}/views/{id}` and `…/elements/{id}`, `archimate://metamodel` (layers and types, impact propagation) | as above, `GET /metamodel` (BL-50) | 2 | done |
| MCP-13 | Prompts: "impact of a change", "describe a view", "model quality review" | none | 2 | done |
| MCP-14 | HTTP transport (streamable HTTP) with its own token (D2, D5) | none | 0 (done) | done |
| MCP-15 | Write tools: create/update/delete elements, relationships, properties, and filing in folders (D11 to D21), 1.3.0. The API's `RELATIONSHIP_RULES` applies: the `warnings` of an answer are passed on, and a `422 RELATIONSHIP_NOT_ALLOWED` with what would be allowed | element/relationship/property/organization endpoints | 4 | done |
| MCP-16 | Model tools: import a file, export to a file, dry-run check, refresh a linked model (D4) | `/models/import`, `/export`, `/link/update` | 4 | parked (2026-10-25) |
| MCP-17 | Scripts and documents of the table above, install package, deploy | none | 0 (done), 5 | done |
| MCP-18 | `model_quality`: the API's quality report (1.1.0) | `GET /analysis/quality` (HLP-10) | after 1.0.0 | done |
| MCP-19 | `relationship_matrix`: direct or along a path pattern, paths as chains (1.1.0) | `POST /graph/matrix` (HLP-11) | after 1.0.0 | done |
| MCP-20 | `landscape`: the hierarchy below roots, for landscape maps (1.1.0) | `POST /graph/hierarchy` (HLP-12) | after 1.0.0 | done |
| MCP-21 | `allowed_relationships`: what ArchiMate allows between two concepts; `model_quality` with `relationshipsNotAllowed` (1.2.0) | `GET /metamodel/relationships` (BL-51) | after 1.0.0 | done |
| MCP-22 | `apply_changes`: many changes in one transaction, `@ref` between them, `expected_revision` (1.4.0; the second step of D18) | `POST /models/{id}/changes` (BL-13, API 3.9.0) | 4 | done |
| MCP-23 | `create_model`: a new, empty model with Archi's top-level folders (1.4.0); only with a key that may create models | `POST /models`, `POST /organizations` | 4 | done |
| MCP-24 | `create_folder`, `update_folder` (rename, move), `delete_folder` (empty, or its contents moved first) (1.5.0) | `/organizations` (POST, PUT, DELETE) | 4 | done |
| MCP-25 | Folders in `apply_changes`: create, rename, move and delete folders in the same transaction, and file new items in a folder made by an earlier change (`@ref`) | `POST /changes` with folder operations (BL-52) | 4 | done (1.6.0) |
| MCP-26 | The model itself: `update_model` (name, documentation) and its properties (`set_property` / `remove_property` with `kind=model`) | `PUT /models/{id}`, `/models/{id}/properties` | 4 | done (1.6.0) |
| MCP-27 | Property definitions: rename one, change its data type, delete one no longer used (today `set_property` only creates them, as strings) | `/property-definitions` (PUT, DELETE) | 4 | done (1.6.0) |
| MCP-28 | Views: create, rename and delete views, add and remove the elements and relationships they show, drill-down links. **Decided 2026-10-29 (D22):** the layout stays in the Browser. `propose_view` answers a Browser link to a generated diagram that the user arranges and saves there (*Save as view*, BR-25); `update_view` and `delete_view` change only *created* views; `list_views` and `get_view` show a view's origin. Design: the API's `CREATED_VIEWS.md` | `origin`, `/views` with `content`, `/changes` view operations (API BL-56, done in 3.15.0); Browser BR-25 done in 2.22.0, the name in a link (`vn=`) in 2.22.1 | done (1.9.0) | done |
| MCP-30 | Each HTTP client with its own API key (`CLIENT_KEYS`), the write tools by that client's role; `X-Client` (1.7.0) | `/auth/me` per key; API 3.11.0 | epic stage 1 (MU-2) | done |
| MCP-31 | `model_history`: who changed what, from the API's record of changes; `changes.log` off by default (1.7.0) | `GET /models/{id}/history` (API 3.11.0) | epic stage 1 (MU-16, MU-17) | done |
| MCP-32 | Safe concurrent writes: `version` in the answers, `expected_version` in the write tools and `apply_changes`, a refused write explained with who changed what (1.8.0) | `If-Match`, `expectedVersion`, `412` with `lastChange` (API 3.12.0) | epic stage 2 (MU-8, T6) | done |
| MCP-33 | Where a model is mastered: `master` and `editedSinceImport` in `list_models` and `model_overview`, refusals on a linked model that say what to do instead (1.10.0) | `link`, `editedSinceImport` in the models' answers (BL-58, API 3.16.0) | after 1.9.0 | done |
| MCP-34 | Resources that announce their change: `subscriptions/listen`, `resources/subscribe`, told from the API's change events (1.11.0) | `GET /api/v2/events` (API 3.17.0) | epic stage 3 (MU-15) | done |
| MCP-35 | Images of diagrams for reports: `diagram_image` saves a view, chosen elements or the diagram of a `browserLink` as PNG or SVG, drawn by the Browser in Chrome or Edge without a window, from a Browser server of the MCP server's own (1.12.0). **Decided 2026-11-09:** the Browser draws (its render mode), rather than PlantUML or a second renderer, so that the images are the Browser's own | Browser 2.29.0 (render mode, `serve.py --port 0 --exit-with-stdin`); no API change | after 1.11.0 | done |
| MCP-29 | What was left out on purpose: `delete_model` (a whole model, only with an admin key), the model's metadata blocks, and the Browser's helpers (expansion counts, model-wide drill-down links). **Needs the user's decision**: which of them, if any, and for `delete_model` how the assistant asks first (it cannot be undone) | `DELETE /models/{id}`, `/models/{id}/metadata`, `/graph/expansion-counts`, `/view-links` | later | parked (2026-10-25) |

## Phases

1. **Phase 0: the frame (done, 0.1.0).** Git repository, the scripts and documents of
   [What it is made of](#what-it-is-made-of), settings, the API client
   with the version and key check, an empty server that starts over stdio,
   the test harness (an in-memory MCP client; the sibling ArchiMate API on a
   scratch SQLite database with the test models of the API, found the way
   the browser finds it).
2. **Phase 1: reading (MCP-1 to MCP-7) (done, 0.2.0).** Enough for "what
   is in this model" and "tell me about X". Tried on the real model (about
   1,000 elements, 1,500 relationships, 70 views): every tool answers in
   under a second; the longest answer, a search with 100 results per group,
   is about 27,000 characters. Left: registering it in Claude Desktop and
   Claude Code and trying it there (by hand).
3. **Phase 2: analysis (MCP-8 to MCP-13) (done, 0.3.0).** `impact_analysis`,
   `find_paths`, `neighbourhood`, `subgraph`, `browser_link`; links to the
   browser in the answers of `get_element`, `get_view`, `browse_folders`
   and the graph tools (`BROWSER_URL`); four resources, three prompts.
   Every kind of link was opened in the browser against the real API and
   drew the right diagram. On the real model the graph tools answer in
   about 0.1 s. Dropped from MCP-12: the table of the relationships
   ArchiMate allows between two element types; neither the API nor the
   browser has it (IMPROVEMENTS.md).
4. **Phase 3: HTTP (MCP-14):** done in phase 0. Left for this phase: try
   it from a second machine.
5. **Phase 4: writing (MCP-15, MCP-16),** decided on 2026-10-24 (D11 to
   D21). Write tools are off unless `ALLOW_WRITE=true` *and* the key's role
   allows them; destructive ones say so in their MCP annotations, so
   clients ask the user first. MCP-15 first, as 1.3.0, for one writer at a
   time and with no change to the API: `create_element`, `update_element`,
   `delete_element`, `create_relationship`, `update_relationship`,
   `delete_relationship`, `set_property`, `remove_property`, `file_item`.
   Several writers at once, and the server used by several people over
   HTTP, are one epic across the three projects: the API's
   `EPIC_MULTIUSER.md`.
6. **Phase 5: release 1.0.0 (done).** The server, registered in Claude
   Code, was asked about real models; that found two faults (ids sent as
   numbers were refused; the API's error messages arrived as a raw dict),
   fixed with two smaller things (a warning for keys that may write, no
   empty `matchedIn`). README complete, install package
   built and deployed into an empty folder and over that installation,
   CHANGELOG.

## Tests

* Unit tests: the API client against a mocked transport (`httpx.MockTransport`),
  the answer formatting, the settings and `.env.example`.
* Tool tests: an in-memory MCP client lists the tools and calls each one
  against the real API, started from `../ArchiMateAPI` on a throwaway SQLite
  file with the API's test models.
* The real model only through `REAL_MODEL_XML`, as in the API; it is never
  committed and its names stay out of the documents.

## Risks

* **Answer size.** A whole model or view can be far too large for an
  assistant's context. Every tool has a limit and says when it cut; views
  come as element and relationship lists, never with coordinates.
* **Wrong element chosen.** Names repeat. Tools that take a name refuse an
  ambiguous one and list the candidates instead of guessing.
* **Writing by mistake.** Write tools are off by default (Phase 4).
* **MCP is still moving.** The SDK and the HTTP transport change often; the
  SDK is held below its next major version (`mcp>=2.3.0,<3`), and the API's
  `runtests.ps1 -WithClients` runs this suite with every check of the API.

## Decisions

Taken on 2026-10-23: the recommendation, the first option (in bold), in
every case.

| ID | Question | Options |
| --- | --- | --- |
| D1 | Language | **Python** with the official MCP SDK (`mcp`, FastMCP), the same toolchain as the API · TypeScript SDK |
| D2 | Transport | **Both**: stdio for an assistant on the same machine (default), streamable HTTP for a shared server · stdio only · HTTP only |
| D3 | Clients to document and test | **Claude Desktop and Claude Code** · also others (VS Code / Copilot, Cursor, …) |
| D4 | Reading or writing | **Read-only for 1.0.0**, writing in a later release · reading plus element/relationship/property changes · also import/export/link |
| D5 | Keys | **One API key per installation, in `.env`** (a reader key by default); over HTTP the MCP server has its own token · over HTTP each user sends their own API key, passed through |
| D6 | Which model | **Every tool takes a model** (id or name), with an optional `DEFAULT_MODEL` setting · always one fixed model per installation |
| D7 | Links to the ArchiMate Browser | **Yes**, when `BROWSER_URL` is set · no |
| D8 | Diagrams | **No images**: views as lists, plus a browser link (D7) · PlantUML source of a view · rendered images |
| D9 | Versions | **Semantic versions from 0.1.0**, 1.0.0 at the end of Phase 5, CHANGELOG like the API's · dated sections like the browser's |
| D10 | Port of the HTTP server | **8100** (API 8000, browser 8090) · other |
| D11 | How writing is switched on (MCP-15) | always · a setting · **a setting and a key that may write**: `ALLOW_WRITE=true` and an API key with the role `editor` (from `/auth/me` at start); otherwise the write tools are not offered |
| D12 | What can be written first | elements and relationships · **plus their properties and their folders** · plus views (nodes, positions). Views stay with the Browser's layouts; whole models are MCP-16 |
| D13 | Deleting | none · deletes marked destructive · **deletes marked destructive; an element that has relationships or is shown in views only with `cascade=true`**. Each answer lists what went with the item |
| D14 | Confirmation | **the client's approval of each tool call** (deletes are annotated destructive) · also a preview-then-confirm step |
| D15 | Two writers at once | ~~the last write wins for now~~; each answer gives the model's new revision · `expectedRevision` on every write (an API change). **Replaced in 1.8.0** by item versions (`expected_version`, API 3.12.0; T6 of the API's `EPIC_STAGE2_DECISIONS.md`) |
| D16 | XMI identifier of a new item | **made by the server**: `id-` and a random UUID, as Archi does; an optional parameter gives one · always given by the assistant |
| D17 | Where a new item is filed | nowhere · **a folder the assistant names, else the default folder**: the top-level folder of the element's layer (Business, Application, …, as Archi names them), "Relations" for relationships; without one it stays unfiled and the answer says so |
| D18 | Many changes in one call | **one item per call first**; a batch that succeeds or fails as a whole once the API has bulk endpoints (BL-13): done in 1.4.0 (`apply_changes`) · a batch without rollback |
| D19 | Checks before writing | only the API's · **also a warning for a likely duplicate** (same type and name), never a refusal. ArchiMate's rules stay with the API (`RELATIONSHIP_RULES`); a refusal is passed on with what would be allowed |
| D20 | Record of changes | none · **a line per write in the server's log** (time, key name, tool, model, item, what changed) · a change log in the API (the multi-user epic) |
| D21 | Undo | **none**: the answers and the log say what changed; exporting a model before larger changes comes with MCP-16 · undo in the server |
| D22 | Views (MCP-28; D12 left them to the Browser) | **the layout only in the Browser**: the MCP server proposes a view as a Browser link, the user saves it there; it renames and deletes created views, never source views (decided 2026-10-29, the API's `CREATED_VIEWS.md`) · a layout service in the API · a grid in the MCP server |
