# ArchiMate MCP

An [MCP](https://modelcontextprotocol.io) server for the ArchiMate API:
an AI assistant such as Claude Desktop or Claude Code uses it to read the
ArchiMate models the API holds and, when writing is switched on, to change
them.

It is the third tool next to the **ArchiMate API** (the models, in a database,
behind a REST API) and the **ArchiMate Browser** (a web page that shows
them). Like the browser it is only a client of the API: it uses nothing but
`/api/v2`, with an API key of its own.

> **Version 1.15.0.** The tools read models, elements, relationships,
> views and folders, answer how elements depend on each other, and give the
> API's reports; answers link to the ArchiMate Browser, `propose_view`
> hands a new view to it, and `diagram_image` saves a diagram as a PNG or
> SVG file for reports ([Images of diagrams](#images-of-diagrams)). With writing switched on (off by default) the
> assistant can also create, change and delete elements, relationships,
> properties, folders and created views: see [Writing](#writing). Others may
> write at the same time: changes are checked against the versions read,
> and subscribed resources are told when a model changes
> ([Resources](#resources)). [PLAN.md](PLAN.md) says how it was built and
> what is left.

| Document | What it holds |
| --- | --- |
| [PLAN.md](PLAN.md) | The plan: tools, phases, decisions, progress |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each version |
| [ACCESS_RIGHTS.md](ACCESS_RIGHTS.md) | Points to the guide to keys and roles in the API's folder |
| [REAL_USE_TESTS.md](REAL_USE_TESTS.md) | Prompts to try the server in Claude on your own models, and what to report |
| [IMPROVEMENTS.md](IMPROVEMENTS.md) | Ideas for after 1.0.0 |
| The API's [EPIC_MULTIUSER.md](../ArchiMateAPI/EPIC_MULTIUSER.md) | The multi-user epic: own keys and `model_history` (1.7.0), versions (1.8.0), notifications (1.11.0) |

## Quick start

You need Python 3.10 or newer and a running ArchiMate API, 3.12.0 or newer
(3.15.0 for created views, 3.16.0 for `editedSinceImport`, 3.17.0 for
notifications of subscribed resources).

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows - source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
copy .env.example .env           # Windows - cp on macOS/Linux
# edit .env: API_URL of the ArchiMate API and API_KEY, a key of it
python run_server.py check       # does the API answer, and take the key?
python run_server.py config      # how to add the server to Claude Desktop / Claude Code
```

On Windows, `archimatemcp.bat install` does all of this.

Give the server a key of its own with the role `reader`: every reading
tool works with it. Writing needs a key with the role `editor` and
`ALLOW_WRITE=true` (see [Writing](#writing)). How to make a key and give it
a role: the guide [ACCESS_RIGHTS.md](../ArchiMateAPI/ACCESS_RIGHTS.md) in the
API's folder.

What to ask, once a client is connected (see below), for example:

* *Which models are there, and what does the biggest one hold?*
* *What is ERP, what does it serve, and on which views is it?*
* *What would a change of Kafka affect, two levels deep? Give me the
  browser link.*
* *How is the Web Shop connected to the ERP?*
* *Describe the view Overview.* (or the prompt `describe_view`)

## Command-line script (Windows)

`archimatemcp.bat` may sit in the project folder or next to it.

| Command | What it does |
| --- | --- |
| `archimatemcp.bat install` | Creates `.venv`, installs the packages, creates `.env` from `.env.example` (and opens it in Notepad), checks the API, prints the client configuration |
| `archimatemcp.bat deploy C:\Apps\ArchiMateMCP [start]` | From an unzipped install package: installs into that folder, or updates the installation there. See [Installing and updating with deploy](#installing-and-updating-with-deploy) |
| `archimatemcp.bat start` | Serves MCP clients over HTTP, at `http://HOST:PORT/mcp` |
| `archimatemcp.bat stdio` | Serves one MCP client over stdin/stdout. MCP clients start the server themselves (see [Connecting a client](#connecting-a-client)); this is for trying it by hand |
| `archimatemcp.bat check` | Checks that the API answers, is 3.12.0 or newer, and takes the key |
| `archimatemcp.bat config` | Prints how to add the server to Claude Desktop and Claude Code, with this installation's paths |

Without the script: `python run_server.py stdio | http | check | config`
(or `python -m app …` in the project folder).

## Configuration

Settings come from environment variables or from `.env` in the project
folder: the server reads that `.env` wherever it is started from, since MCP
clients start it in a folder of their choosing. A setting `.env.example`
does not name stops the server at start (a typo would otherwise go
unnoticed).

| Setting | Default | What it is |
| --- | --- | --- |
| `API_URL` | `http://127.0.0.1:8000` | Root URL of the ArchiMate API, without `/api/v2` |
| `API_KEY` | empty | A key of the API. The role `reader` is enough for reading; writing needs `editor` |
| `API_TIMEOUT` | `60` | Seconds one request to the API may take |
| `HOST` | `127.0.0.1` | Address of the HTTP transport. A loopback address listens on `127.0.0.1` and `::1` |
| `PORT` | `8100` | Port of the HTTP transport (the API has 8000, the browser 8090) |
| `MCP_TOKEN` | empty | The token HTTP clients send as `Authorization: Bearer <token>`; they all work with `API_KEY`. This or `CLIENT_KEYS` is required unless `HOST` is a loopback address |
| `CLIENT_KEYS` | `false` | `true` (1.7.0): every HTTP client sends its own key of the ArchiMate API as `Authorization: Bearer <key>`, and the server works with that key for that client. `API_KEY` may then stay empty |
| `DEFAULT_MODEL` | empty | The model the tools read when the assistant does not say which: an id or a name. Empty: the only model there is; with several, the tools ask |
| `MAX_RESULTS` | `100` | Most items in one list of an answer (1 to 1000). The larger, the more of the assistant's context one answer takes; tools take a smaller `limit` |
| `BROWSER_URL` | empty | The ArchiMate Browser as its users open it, e.g. `http://127.0.0.1:8090/`. When set, answers carry a `browserLink` that opens what they describe as a diagram there. Empty: no links |
| `ALLOW_WRITE` | `false` | With `true` and a key with the role `editor`, the write tools are offered; see [Writing](#writing) |
| `CHANGE_LOG` | empty | The file every write is recorded in, one JSON line each, relative to the server's folder. Empty (the default since 1.7.0): the server's log only; the API's record of changes counts |
| `BROWSER_DIR` | empty | The ArchiMate Browser's folder (2.29.0 or later), which draws the images of `diagram_image` (1.12.0). Empty: `ArchiMateBrowser` next to this server's folder |
| `IMAGE_DIR` | `images` | Where `diagram_image` saves files, relative to the server's folder; the tool's file names stay inside it |
| `RENDER_BROWSER` | `auto` | The browser that draws: `auto` (Chrome, else Edge), `chrome`, `msedge`, or the path of a Chromium-based browser's `.exe` |
| `RENDER_TIMEOUT` | `120` | Seconds one diagram may take to draw |
| `RENDER_IDLE` | `300` | Seconds without an image after which the browser and the Browser server it uses stop; `0`: they run until the MCP server stops |

At start the server asks the API's `/health` and `/api/v2/auth/me`. An API
older than 3.12.0 or a key it refuses stops the server with a message; an API
that does not answer yet only gives a warning, and the tools fail until it
does.

### Keys and tokens

* **The API key stays on the server.** It is in `.env`, never in a client's
  settings, and the API sees every request of the MCP server as coming from
  that key.
* **Over HTTP, either each client sends its own API key** (`CLIENT_KEYS=true`,
  1.7.0): the server asks the API whose key it is and works with it for
  that client, so the API's record of changes names the person and the
  write tools follow their role; **or all clients send `MCP_TOKEN`**, a
  secret of the MCP server, and work with its `API_KEY`. With neither, the
  server only listens on a loopback address; with `HOST=0.0.0.0` it refuses
  to start. Make a token with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
* **Over stdio** the key in `.env` is used: on a person's own machine, put
  their own key there.
* `GET /health` answers without the token (for scripts that check the
  server runs); it tells only the version.

## Connecting a client

`archimatemcp.bat config` prints the lines below with the right paths.

### Claude Desktop

Claude Desktop starts the server itself, over stdio. In *Settings →
Developer → Edit Config*, add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "archimate": {
      "command": "C:\\Apps\\ArchiMateMCP\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Apps\\ArchiMateMCP\\run_server.py", "stdio"]
    }
  }
}
```

and restart Claude Desktop. `run_server.py` rather than `python -m app`:
the client does not set the working directory.

### Claude Code

Over stdio (Claude Code starts the server):

```bash
claude mcp add archimate --scope user -- "C:\Apps\ArchiMateMCP\.venv\Scripts\python.exe" "C:\Apps\ArchiMateMCP\run_server.py" stdio
```

Over HTTP (the server runs on its own, `archimatemcp.bat start`):

```bash
claude mcp add --transport http archimate --scope user http://127.0.0.1:8100/mcp --header "Authorization: Bearer <MCP_TOKEN>"
```

With `CLIENT_KEYS=true` the header carries your own key of the ArchiMate
API instead. Claude Desktop's remote connectors sign in with OAuth, which
the server does not offer yet (stage 4 of the multi-user epic): use Claude
Desktop over stdio, with your own key in `.env`.

`--scope project` instead writes `.mcp.json` in the current project, for
everyone who works on it.

## The tools

The tools below only read, and say so to the client (`readOnlyHint`), except
`diagram_image`, which writes image files (and changes no model). The write
tools are described in [Writing](#writing).

| Tool | What it answers |
| --- | --- |
| `list_models` | The models: id, name, revision, how many elements, relationships and views, where each is mastered (`master`: `file` or `api`, 1.10.0), and the file a linked model is updated from |
| `model_overview` | What a model holds: elements by layer and type, relationships by type, views, the top-level folders with their counts, the properties in use with their most frequent values; where it is mastered, with the file it is linked to or the changes made since its last import (`editedSinceImport`) |
| `search` | Elements, relationships and views by text (in names, documentation or property values), element type, layer, relationship type, or property value. Ranked: an equal name first |
| `get_element` | One element: documentation, properties, the folders it is filed in, its relationships out and in with the element at the other end, the views that show it |
| `get_relationship` | One relationship: type, name, documentation, properties, source and target, the views that show it |
| `list_views` | The views of a model, those whose name contains a text, or those that show an element; `origin` keeps the source's or the created ones. A recipe (API 3.22.0) gives its `recipe` |
| `get_view` | What a view shows: its elements (and which are drawn inside which), the relationships between them, its groups and notes, its links to other views. No coordinates. Where it comes from (`origin`: the model's source, or created, with who made it and what an update took out of it) (1.9.0). A recipe (1.13.0, API 3.22.0) has no drawing: the answer gives its recipe and the link that draws it |
| `propose_view` | A link that opens chosen elements (and relationships) as a diagram in the ArchiMate Browser, with *Save as view…* and a name filled in; nothing is stored, the user arranges and saves it there. Needs `BROWSER_URL` (1.9.0, MCP-28) |
| `browse_folders` | The folder tree, one level at a time: sub-folders with their counts, and what is filed directly in a folder |
| `impact_analysis` | What a change of elements affects, or what they depend on, level by level, each element with the relationship it is reached over. Follows the API's propagation rules (`archimate://metamodel`) |
| `find_paths` | How two elements are connected: the shortest paths, each as a readable chain (`Web Shop -Flow-> Kafka -Flow-> ERP`) and as steps |
| `neighbourhood` | The elements within some relationships of given elements, with their distance, and the relationships among them. `incoming_types` / `outgoing_types` (1.15.0, API 3.24.0) follow only those relationship types in that direction, at every step, e.g. every incoming relationship but outgoing only Serving and Realization |
| `subgraph` | A set of elements and the relationships among them: given elements, a folder's, a view's, every element of a type or layer |
| `browser_link` | A link that opens a diagram (of elements, a view, a folder) in the ArchiMate Browser, optionally with an element selected |
| `diagram_image` | A diagram saved as a PNG or SVG file, drawn exactly as the ArchiMate Browser draws it: a view, chosen elements, or the diagram of a `browserLink` from another answer. Answers the files' paths and sizes; see [Images of diagrams](#images-of-diagrams) (1.12.0, MCP-35) |
| `check_recipe_script` | What a recipe script would make, without changing anything: every error with its line and a suggestion, or each recipe (new, changed, unchanged, obsolete) with a `browserLink`. Its description holds the language in short; the whole of it is the API's [RECIPE_SCRIPTS.md](../ArchiMateAPI/RECIPE_SCRIPTS.md) (1.15.0, API 3.24.0) |
| `model_quality` | What is probably unfinished or wrong: elements in no view or without relationships, unfiled items, duplicate names within a type, empty views, empty labels, relationships ArchiMate does not allow between their ends |
| `relationship_matrix` | Which elements of one set connect to which of another, directly or along a path pattern (e.g. Realization, then Serving); each pair with its count and its paths as readable chains |
| `landscape` | A landscape map as a tree: the elements below root elements along nesting relationships (e.g. capabilities with the applications that realize them), with property values and a legend |
| `allowed_relationships` | Which relationship types ArchiMate allows from one element type to another, or from one type to every other (the table Archi uses) |
| `model_history` | Who changed what in a model, and when: for one element, relationship or view, one user, a time span; each change with the client, and the fields before and after (1.7.0, API 3.11.0). Offered with a key that may write |
| `api_status` | The API's URL and version, and the name, label and role of the key in use. For when other tools fail |

How the tools are told what to look at:

* **The model:** every tool takes `model`, an id or a name (or part of
  one). Ids may come as numbers or as text, as clients send them. It may be left out when there is only one model, or `DEFAULT_MODEL`
  is set; otherwise the tool lists the models and asks.
* **Elements and views** are given by id, XMI identifier or name; a name
  equal to the text wins over names that contain it. **Relationships** by
  id or XMI identifier (`get_element` lists them). **Folders** by id, by
  path (`Business/Processes`) or by a name only one folder has.
* **A name that matches several things is refused**, with the candidates
  and their ids, so that the assistant asks again with an id. It never
  guesses.
* **Lists stop at `MAX_RESULTS`** (or a smaller `limit`), and then say
  `"truncated": true` with the `total`. `landscape` stops at five times
  `MAX_RESULTS` elements.
* **Sets of elements** (`relationship_matrix`, `landscape`) are given as one
  of `elements` (ids, XMI identifiers or names), `element_type`, `layer`,
  `folder` or `view`, narrowed by `element_types` and a property.

Answers are JSON: the structured content of the result, and the same as
compact text for the assistant to read (the SDK would indent it, which
makes a long answer about 1.7 times as long).

### Writing

Off by default. With `ALLOW_WRITE=true` in `.env` **and** an API key with
the role `editor` (or `admin`), the server also offers these tools; with a
reader key it says so at start and offers none of them (decision D11).

| Tool | What it does |
| --- | --- |
| `create_element` | Creates an element (type, name, documentation, properties) and files it |
| `update_element` | Changes an element's name, documentation or type |
| `delete_element` | Deletes an element; one with relationships or shown in views only with `cascade=true`, and the answer lists what went with it |
| `create_relationship` | Creates a relationship between two elements, or with a relationship as an end (`source_relationship`, `target_relationship`), and files it |
| `update_relationship` | Changes a relationship's type, name, documentation, ends or attributes |
| `delete_relationship` | Deletes a relationship; the relationships attached to it go with it |
| `set_property` | Sets a property of an element, relationship or view, or of the model itself (`kind=model`), in a language if given; a new name makes a new property definition |
| `remove_property` | Removes a property's values |
| `file_item` | Files an element, relationship or view in a folder, moving it from where it was |
| `create_folder` | Creates a folder in a folder, or at the top level; one of the same name in the same place is refused |
| `update_folder` | Renames a folder, changes its documentation, or moves it with everything in it |
| `delete_folder` | Deletes an empty folder; one that is not empty only with `move_contents_to`, where its sub-folders and items go. Nothing but the folder is deleted |
| `update_view` | Renames a view or changes its documentation: a created view or recipe (1.9.0), or a view of the model's source on a model mastered here (1.14.0, API 3.23.0) |
| `delete_view` | Deletes a view, after asking: a created view or recipe (1.9.0), or a view of the model's source on a model mastered here (1.14.0) |
| `run_recipe_script` | Makes and updates the recipes of a recipe script, in one change, after `check_recipe_script` and the user's yes; `delete_obsolete` also deletes those the script no longer makes. Running it again updates its own recipes. A script with errors changes nothing and is answered like a check (1.15.0, API 3.24.0) |
| `apply_changes` | Many of the changes above in one call and **one transaction**: all of them, or none, folders included (1.6.0). Later changes name items and folders created by earlier ones as `@ref` |
| `create_model` | A new, empty model, by default with Archi's top-level folders. Only with a key that may create models (role `admin`) |
| `update_model` | Changes the model's name, documentation or version label. Only with a key that may change models (role `admin`) |
| `update_property_definition` | Renames a property or changes its data type, for all its values |
| `delete_property_definition` | Deletes a property definition; one with values only with `with_values=true`, after asking |

* **Many changes at once: `apply_changes`** (1.4.0, on the API's changes
  in one transaction). For example a piece of a model built in one call:

  ```json
  [ {"op": "createElement", "ref": "crm", "type": "ApplicationComponent", "name": "CRM"},
    {"op": "createElement", "ref": "sell", "type": "BusinessProcess", "name": "Sell"},
    {"op": "createRelationship", "type": "Serving", "source": "@crm", "target": "@sell"},
    {"op": "updateElement", "element": "Old CRM", "name": "Legacy CRM"} ]
  ```

  The first change that fails undoes all of them, and the error names it
  ("Operation 3 (createRelationship): …"). `expected_revision` (the
  `revision` of an earlier answer) applies the changes only if nobody
  changed the model since. The single tools stay for one change at a time.
* **New items** get an XMI identifier like Archi's (`id-` and a random
  UUID) and are filed in the top-level folder of their layer as Archi names
  them (*Business*, *Application*, *Technology & Physical*, …;
  *Relations* for relationships), unless the call names a folder. Without
  such a folder the item stays unfiled, and the answer says so (D16, D17).
* **Likely duplicates** (an element of the same type and name, the same
  relationship between the same ends) are reported as a warning; the item
  is created anyway (D19).
* **The API decides what is allowed:** the key's role, linked models (read
  only), and ArchiMate's relationship rules (`RELATIONSHIP_RULES` of the
  API, 3.8.0). A refusal reaches the assistant with what would be allowed.
  A model linked to a file (`master` `file`) is changed in Archi; the
  refusal says so, and that unlinking the model makes it editable here
  (1.10.0).
* **Clients ask before deletes:** they are marked destructive
  (`destructiveHint`); the other write tools are marked as not read-only, so
  clients ask as they are set up to (D13, D14).
* **The record of changes:** the API records every change with who made
  it (3.11.0); `model_history` reads it. The server's own JSON line per
  write goes to its log, and to `changes.log` when `CHANGE_LOG` names it
  (D20; off by default since 1.7.0). Every answer gives the model's new
  revision.
* **Others may write at the same time** (1.8.0, API 3.12.0): `get_element`,
  `get_relationship`, `get_view` and `browse_folders` answer an item's
  `version`, and the write tools take it as `expected_version`. A change of
  an item someone changed since the assistant showed it to the user is
  refused, nothing is changed, and the assistant is told who changed what,
  and to tell the user and ask. Without `expected_version` a tool uses the
  version it reads in the same call, just before writing (every write tool
  and every change of `apply_changes`, 1.12.0): that catches only a change
  made during the call. So an API with `REQUIRE_IF_MATCH=true`, which
  refuses a change that says no version, takes every write of this server;
  `api_status` shows whether it is on (`requireIfMatch`, API 3.21.0).
* **No undo** (D21).

### Links to the ArchiMate Browser

With `BROWSER_URL` set, `get_element` (the element selected), `get_view`,
`browse_folders` and the graph tools add a `browserLink` to their answers,
and `browser_link` makes one on request. The link is the browser's own
shareable link (its README, *Basket and shareable diagram links*): it
names items by XMI identifier, so it keeps working after the model is
replaced with a new version of its file. A neighbourhood deeper than 3, or
an answer narrowed by filters the browser's link cannot carry, gets a link
to the model only.

### Images of diagrams

`diagram_image` (1.12.0, MCP-35) saves a diagram as a file, for reports
and documents: the assistant puts the file it names into the document. The
ArchiMate Browser draws it, so the picture is the Browser's own: a stored
view with its positions, nesting and colours, a generated diagram laid out
by ELK with the Browser's rules.

* **What is drawn:** one of `view` (as it is stored), `elements` (with the
  relationships between them), or `link`, a `browserLink` of another answer
  (`neighbourhood`, `impact_analysis`, `find_paths`, `subgraph`,
  `propose_view`...): that diagram, with the filters it carries. A link needs
  `BROWSER_URL` for the other tools to give one; `view` and `elements` do not.
* **How:** `format` `png` (default), `svg` or `both`; `direction` `TB` or `LR`
  and `nesting` (`none`, `composition`, `assignment`) for a generated diagram;
  `scale` for the PNG's pixels per unit (2: sharp in print); `file`, the name
  without extension inside `IMAGE_DIR` (sub-folders allowed; default: the
  diagram's title; a file of that name is replaced). `preview` also returns a
  small PNG for the assistant to look at.
* **The answer:** the title, the files with their paths, sizes in pixels and
  bytes, the diagram's info line (how many elements and relationships), and
  a `browserLink` when `BROWSER_URL` is set. A diagram too large for a
  browser's canvas gets a smaller PNG scale, which the answer says; the SVG
  has no such limit.

How it works (`app/render.py`): the first image starts a **Browser server of
the MCP server's own**, `server/serve.py` of `BROWSER_DIR` on a free port of
127.0.0.1, and **Chrome or Edge without a window** through
[Playwright](https://playwright.dev/python/) (it uses the installed browser
and downloads none), with a profile that is thrown away. The page is the
Browser in its render mode (`…/?render`, the Browser's README, *Images for
the MCP server*). The Browser need not be running, and its own settings and
`.env` are not used. The Browser server holds no key: every request of the
page carries the key the tool works with (with `CLIENT_KEYS`, the client's)
in its `X-API-Key` header, so the key is in no URL, command line or file.
Both stay for `RENDER_IDLE` seconds after the last image, so a report with
many diagrams starts them once: the first image takes a few seconds, the
next about one each. They end with the MCP server, also when it is stopped
abruptly. Images are made one at a time.

Needs the Python package `playwright` (in `requirements.txt`), Google Chrome
or Microsoft Edge (Edge comes with Windows), and the ArchiMate Browser 2.29.0
or later; the tool's error says which is missing. Over HTTP the files are
written on the machine the MCP server runs on.

## Resources

Data a user can attach to a conversation (in Claude Desktop: the "+" menu).

| URI | Content |
| --- | --- |
| `archimate://metamodel` | The layers with their element types, the relationship types, how the impact analysis propagates a change along each (the API's `GET /metamodel`) |
| `archimate://models` | The models: id, name, XMI identifier, revision |
| `archimate://models/{model}/views/{view}` | A view, as `get_view` answers |
| `archimate://models/{model}/elements/{element}` | An element, as `get_element` answers |

**Subscribing** (1.11.0, with the ArchiMate API 3.17.0). A client may
subscribe to resources: with `subscriptions/listen` (protocol 2026-07-28) or
`resources/subscribe` (earlier versions). While anyone subscribes, the
server listens to the API's change events and tells the subscriber that a
resource may have changed: `archimate://models` by a change of any model,
an element or a view by any change of its model (its answer holds the
relationships, properties and names around it), the metamodel never. With
nobody subscribed the server opens no stream; with an API without events
subscriptions are taken but never told. The tools read fresh on every call
and need none of this.

## Prompts

Ready-made requests (in Claude Code: `/mcp__archimate__<name>`; in Claude
Desktop: the "+" menu). They tell the assistant which tools to use and what
to answer with.

| Prompt | Arguments | What it asks for |
| --- | --- | --- |
| `impact_of_change` | `element`, `model` | What a change of the element affects and what it depends on, by layer, with risks and the browser link |
| `describe_view` | `view`, `model` | A description of a view for someone who has not seen it |
| `model_quality_review` | `model` | A review of structure, naming, documentation and views against ArchiMate good practice |

## Architecture

```
app/
  __main__.py      python -m app [stdio | http | check | config]
  config.py        settings (pydantic-settings, unknown settings refused)
  api_client.py    the client of /api/v2: key, timeouts, version check, error messages
  server.py        the MCP server (MCP Python SDK, MCPServer), its instructions, api_status
  lookup.py        what a tool is told to look at: by id, XMI identifier, name or path
  links.py         links to the ArchiMate Browser (its link format)
  tools/           the tools, one module per subject: models, search, concepts, views, folders, graph,
                   reports, metamodel (allowed_relationships), history, images (diagram_image), scripts
                   (check_recipe_script, run_recipe_script), write
  render.py        images of diagrams: its own Browser server, Chrome or Edge without a window (1.12.0)
  resources.py     the archimate:// resources
  watch.py         subscriptions to them, told from the API's change events (1.11.0)
  prompts.py       the prompts
  http.py          the HTTP transport at /mcp: behind MCP_TOKEN, or a server per client key (CLIENT_KEYS); GET /health
  version.py       APP_VERSION, MIN_API_VERSION
run_server.py      starts app.__main__ from any working directory
```

* **The API decides.** The server never reads the database or model files.
  When a tool needs something the API cannot answer well, the API is
  extended (an item in its `IMPROVEMENTS.md`), not worked around here.
* **Errors reach the assistant.** A failed API request becomes a tool error
  with the API's own message (a 404, a 409 with its candidates, a 422 with
  the field at fault), so the assistant can correct its call.
* **Over stdio, stdout is the protocol.** Logging goes to stderr only.

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

or `.\runtests.ps1`, which lints with `ruff` first (`ruff.toml`; it is in
`requirements-dev.txt`). The API's `runtests.ps1 -WithClients` runs it too, so
that a change of the API is tested against this server. The tests start the real ArchiMate API from the folder
next to this one (`..\ArchiMateAPI`, or `ARCHIMATE_API_DIR`) on a throwaway
SQLite database, import the API's synthetic and basic test models, and talk to the MCP
server through the SDK's client: in-process, over stdio (started from a
foreign folder, as a client does) and over HTTP. The API runs with
`ARCHIMATE_API_PYTHON`, else its own `.venv`, else the Python this
project's `.venv` was made from, which then needs the API's packages.
Without the API those tests are skipped, and `runtests.ps1` fails. The write
tools are tested with an editor key, each test on a new model of its own, so
that the reading tests see the test models unchanged. The settings of the
API's own `.env` that change how it answers are set for the test API, so
that they do not reach it. It runs with `REQUIRE_IF_MATCH=true` (1.12.0): a
change that says no version is refused, so the suite shows that every write
tool sends one; the tests' own writes send `If-Match: *`.
`ARCHIMATE_TEST_REQUIRE_IF_MATCH=false` runs the suite against an API that
does not ask; `tests/test_strict.py` then starts a second API that does. `diagram_image` is
tested with the ArchiMate Browser next to this folder (`..\ArchiMateBrowser`,
2.29.0 or later) and the installed Chrome or Edge; without Playwright, the
Browser or a browser those tests are skipped.

## Creating an install package

```powershell
.\createinstallpackage.ps1
```

This creates, under `dist/` by default, `ArchiMateMCP_<timestamp>.zip`:
the package, ready to copy to a target machine and unzip there. The folder
it is put together in is deleted afterwards (`-KeepFolder` keeps it). It
holds `app/`, `run_server.py`, `requirements.txt`, `.env.example`,
`archimatemcp.bat`, `deploy.ps1`, `README.md`, `CHANGELOG.md`,
`ACCESS_RIGHTS.md` and `REAL_USE_TESTS.md`, and `MANIFEST.txt`, the list of
its files for `deploy.ps1`.

The Markdown files in the package (README, CHANGELOG, ...) link to files the
package leaves out, such as the working documents and the other projects'
files. The script rewrites those links to the same file in the project's
public repository on GitHub (`https://github.com/rnovicky/<project>`), so
that they work in an installation; links to files in the package stay
relative.

| Parameter | Default | Purpose |
| --- | --- | --- |
| `-OutputDir` | `dist` (under the project root) | Where the timestamped zip (and folder) are created |
| `-NoZip` | off | Skip zipping; only produce the folder |
| `-KeepFolder` | off | Keep the uncompressed folder next to the `.zip` (under `powershell -File`: `-KeepFolder true` or `1`) |

### Installing and updating with deploy

As for the API (its README, *Installing and updating with deploy*): keep the
server in one fixed folder, e.g. `C:\Apps\ArchiMateMCP`, unzip a new package
anywhere, and run from the unzipped folder:

```bat
archimatemcp.bat deploy C:\Apps\ArchiMateMCP
archimatemcp.bat deploy C:\Apps\ArchiMateMCP start
```

or `.\deploy.ps1 -Target C:\Apps\ArchiMateMCP [-Package <the .zip>] [-Start]`.
It refuses while the server runs: over HTTP (something answers on
`HOST:PORT`), or over stdio for an MCP client (a Python of the
installation's `.venv` still runs; quit Claude Desktop, or end the Claude
Code session). It backs the installation up next to it (without `.venv`),
copies the new files and deletes those the new version no longer has, keeps
`.env` (commenting out settings the new version does not know, and listing
new ones), and installs `requirements.txt` into `.venv`. MCP clients need
no change: they start the new version next time. `start` starts the HTTP
server in a window of its own.

### Installing by hand

```bash
# unzip ArchiMateMCP_<timestamp>.zip, then:
cd ArchiMateMCP_<timestamp>
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env           # edit API_URL and API_KEY
.venv\Scripts\python run_server.py check
.venv\Scripts\python run_server.py config
```

## Development notes

* The MCP Python SDK is 2.x: its high-level server is `MCPServer` (it was
  `FastMCP` in 1.x), and its types use snake_case attributes
  (`result.structured_content`, `read_only_hint`).
* A tool returns a dict with camelCase keys, like the API's JSON;
  `tools.compact` sends it as the structured content and, for the
  assistant to read, as compact JSON text.
* A failure meant for the assistant is raised as `ApiError` or
  `LookupFailed` (both `ToolError`s of the SDK); any other exception reaches
  the client only as "Error executing tool", without its text.
* Parameters that name something are `Ref` (`str | int`): Claude Code sends
  an id as a number, and a `str` parameter refuses it.
* The real model (`../test_data/model.xml`) is tried by hand only, never
  committed, and its names stay out of the documents.

## License

MIT, see [LICENSE](LICENSE). Third-party code keeps its own licence.
