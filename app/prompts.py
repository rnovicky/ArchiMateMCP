"""
MCP-13: prompts, ready-made requests a user picks in the client (a slash
command in Claude Code, the "+" menu in Claude Desktop). Each says which
tools to use and what the answer should hold; the assistant does the work.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from app.tools import Context

ModelArg = Annotated[str, Field(description="The model: id or name; empty when there is only one.")]


def _in(model: str) -> str:
    return f" in the model \"{model}\"" if model.strip() else ""


def register(server: MCPServer, ctx: Context) -> None:  # noqa: ARG001  (the same shape as the tool modules)

    @server.prompt(title="Impact of a change")
    def impact_of_change(
        element: Annotated[str, Field(description="The element that changes: id, XMI identifier or name.")],
        model: ModelArg = "",
    ) -> str:
        """What a change of an element affects, and what it depends on."""
        return f"""Assess what a change of the element "{element}"{_in(model)} would mean.

1. get_element: what the element is, its documentation and properties, its direct relationships.
2. impact_analysis with direction "impact": what a change of it affects; then with "dependencies":
   what it depends on. Start with max_depth 3; go deeper only if level 3 still holds much.
3. Answer with:
   - a short description of the element;
   - the affected elements grouped by layer (business, application, technology...), the nearest
     first, each with the relationship it is reached over;
   - what it depends on, the same way;
   - the risks this suggests (many dependants, a single point of failure, business processes at the
     end of a chain);
   - the browserLink of the impact analysis, if the answer has one, so the user can see it as a diagram.
Say when a list was truncated rather than presenting it as complete."""

    @server.prompt(title="Describe a view")
    def describe_view(
        view: Annotated[str, Field(description="The view: id, XMI identifier or name.")],
        model: ModelArg = "",
    ) -> str:
        """A description of a view (diagram) for someone who has not seen it."""
        return f"""Describe the view "{view}"{_in(model)} for someone who has not seen it.

1. get_view: its elements, which are drawn inside which, its relationships, groups, notes and links.
2. get_element for the two or three elements that the most relationships of the view meet, if their
   documentation would help.
3. Answer with: what the view is for (its viewpoint and documentation), its main parts and how they
   depend on each other, what its notes and groups say, which views it links to, and anything that
   looks incomplete (elements without relationships on the view, empty groups). End with the
   browserLink of the view, if the answer has one."""

    @server.prompt(title="Model quality review")
    def model_quality_review(model: ModelArg = "") -> str:
        """A review of a model's structure and naming against ArchiMate good practice."""
        return f"""Review the quality of the ArchiMate model{_in(model) or ''}.

1. model_overview: the size, the spread over layers and types, the folders, the properties in use.
2. model_quality: elements in no view or without relationships, unfiled items, duplicate names, empty
   views, empty labels, relationships ArchiMate does not allow. Weigh them: an element in no view can be
   on purpose; duplicates seldom are, and a relationship that is not allowed never is (allowed_relationships
   says what would fit).
3. browse_folders: is the folder tree organised (by layer, domain...) or are items piled up?
4. search with a few element types that matter (ApplicationComponent, BusinessProcess, Node...): are
   names consistent (singular, no type in the name, the same language)? Is documentation present?
5. list_views and get_view for two or three views: do they have a clear purpose and viewpoint?
6. Answer with findings ordered by importance, each with examples (names and ids), and concrete
   suggestions. Mention the layers or types that are missing or sparse given the rest of the model.
Base every finding on what the tools returned; say what you did not check."""
