"""
The MCP server: its description for the assistant and its tools.

build_server() makes one server around one ApiClient. `python -m app` runs it
over stdio or HTTP; the tests connect to it in-process.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from app import prompts, resources, watch
from app.api_client import ApiClient
from app.config import Settings
from app.links import BrowserLinks
from app.lookup import Lookup
from app.tools import READ_ONLY, Context, compact, register_all
from app.version import APP_VERSION

INSTRUCTIONS = """\
This server reads ArchiMate models held by the ArchiMate API: models, their
elements, relationships, views (diagrams) and folders.

Start with list_models (which models exist) or model_overview (what a model
holds). Find things with search, then look at them with get_element,
get_relationship and get_view; browse_folders walks the folder tree.
impact_analysis, find_paths, neighbourhood and subgraph answer questions
about how elements depend on each other.

Every tool takes `model` (id or name); it may be left out when there is only
one model. Elements and views may be given by id, XMI identifier or name; a
name that matches several things is refused with the candidates, so ask
again with the id. Ids are the API's and are only valid within their model.
Lists stop at a limit; "truncated": true with "total" says there is more.
When an answer has a "browserLink", offer it to the user: it opens the same
thing as a diagram in the ArchiMate Browser.

Views are either of the model's source (they came with its file; what they
show is never changed) or created views (made in the ArchiMate Browser or
through the API); list_views and get_view say which. You cannot lay out or store a view:
to suggest one, call propose_view and give the user its link; they arrange
the diagram in the Browser and save it there.

For reports and documents, diagram_image saves a diagram as a PNG or SVG
file, drawn as the Browser draws it: a view, some elements, or the diagram of
a "browserLink" from another answer. Put the file it names into the document.
"""

READ_ONLY_NOTE = """
It only reads models: writing is switched off on this server.
"""

WRITE_NOTE = """
It can also change a model: create_element, update_element, create_relationship,
update_relationship, set_property, remove_property and file_item;
create_folder and update_folder organise the folders; update_view renames a
view and delete_view deletes one (a view of the source only on a model mastered here); update_model,
update_property_definition and delete_property_definition change the model
and its property definitions; delete_element, delete_relationship and
delete_folder and delete_view remove things. Ask the user before every delete, and say what
would go with it; when a folder's contents or a cascade need a decision,
ask the user instead of choosing yourself. For more than two or three changes use
apply_changes: all of them in one call and one transaction, all or nothing.
Look before you write: search first, so that you do not create what exists;
allowed_relationships says which relationships ArchiMate allows. New items are
filed in the folder of their layer unless you name one. Say what you changed,
with the ids the answers give; a write cannot be undone here.
Others may change the same model at the same time. get_element,
get_relationship, get_view and browse_folders answer an item's "version":
when you change or delete something you showed the user earlier, pass that
version as expected_version. If someone changed the item since, nothing is
changed and you are told who changed what: read it again, tell the user, and
ask before writing again. Without expected_version a tool checks against the
version it reads itself just before writing, which catches only a change made
during the call, not one made since you showed the item.
Only a model mastered here can be changed: list_models and model_overview say
"master": "api". A model with "master": "file" is linked to a file and updated
from it; its changes are made in Archi, so do not try to write to it (its
created views are the exception: update_view and delete_view work there).
"""


def build_server(settings: Settings, client: ApiClient | None = None, *, writable: bool | None = None,
                 key_name: str = "", permissions: list[str] | None = None) -> MCPServer:
    """`writable`: offer the write tools (D11); the launcher decides it from ALLOW_WRITE and the key's role."""
    api = client or ApiClient(settings)
    writable = settings.allow_write if writable is None else writable
    server = MCPServer(
        name="archimate",
        title="ArchiMate",
        version=APP_VERSION,
        instructions=INSTRUCTIONS + (WRITE_NOTE if writable else READ_ONLY_NOTE),
    )

    @server.tool(annotations=READ_ONLY)
    @compact
    async def api_status() -> dict[str, Any]:
        """The ArchiMate API this server uses: its URL and version, the name and role of the key in use,
        whether this server may write, and whether the API requires every change to say the version it was
        based on (requireIfMatch; the write tools always send one).

        Call it when other tools fail with connection or permission errors.
        """
        status = await api.check()
        return {"server": f"ArchiMate MCP {APP_VERSION}", "apiUrl": status.url, "apiVersion": status.version,
                "keyName": status.key_name, "keyLabel": status.key_label, "role": status.role, "writing": writable,
                "requireIfMatch": status.require_if_match, "clientKeys": settings.client_keys}

    ctx = Context(api=api, lookup=Lookup(api, settings), settings=settings, links=BrowserLinks(settings.browser_url),
                  writable=writable, key_name=key_name, permissions=permissions)
    register_all(server, ctx)
    resources.register(server, ctx)
    server.watcher = watch.Watcher(api, ctx.lookup)  # type: ignore[attr-defined]  # MU-15 (1.11.0)
    watch.install(server, server.watcher)  # resources that announce their change
    prompts.register(server, ctx)
    server.api = api  # type: ignore[attr-defined]  # for the launcher and the tests
    return server
