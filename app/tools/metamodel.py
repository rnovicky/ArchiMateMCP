"""MCP-21 allowed_relationships: which relationships ArchiMate allows between two concepts (API 3.7.0, BL-51)."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from app.tools import READ_ONLY, Context, compact

Concept = Annotated[str, Field(
    description="An element type as the API names it (e.g. ApplicationComponent, BusinessProcess), or "
                "Relationship for a relationship that is the source or target of another one.")]


def register(server: MCPServer, ctx: Context) -> None:
    api = ctx.api

    @server.tool(annotations=READ_ONLY)
    @compact
    async def allowed_relationships(
        source_type: Annotated[Concept | None, Field(description="The source concept; leave out to list every source.")] = None,
        target_type: Annotated[Concept | None, Field(description="The target concept; leave out to list every target.")] = None,
    ) -> dict[str, Any]:
        """Which relationship types ArchiMate 3.2 allows from one concept to another (Appendix B of the
        specification, the same table Archi uses).

        Give both types for one pair, or one of them for every concept on the other side with what it allows.
        Use it to choose a relationship when modelling, or to judge one found in a model (model_quality lists
        the relationships of a model that break these rules). The types of elements are in get_element and
        search answers; archimate://metamodel lists every element type.
        """
        if not source_type and not target_type:
            raise ToolError("Give source_type, target_type or both; the whole table is too long to be useful here.")
        params = {k: v for k, v in (("source", source_type), ("target", target_type)) if v}
        return await api.get("/metamodel/relationships", **params)
