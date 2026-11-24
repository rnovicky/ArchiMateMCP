# Improvements

Ideas for after 1.0.0. Each gets an id (MCP-n, continuing PLAN.md's numbers)
when it is taken up. Items that need the API go to the API's
`IMPROVEMENTS.md` as BL items.

| Idea | Notes |
| --- | --- |
| PlantUML text of a view or of a set of elements | Decision D8: not for 1.0.0; the browser has the mapping (js/plantuml.js) |
| ~~Per-user API keys over HTTP~~ | **Done in 1.7.0** (`CLIENT_KEYS=true`, MCP-30), the multi-user epic's MU-2 |
| OAuth for the HTTP transport | For clients that only connect to OAuth-protected servers, such as Claude Desktop's remote connectors. Stage 4 of the multi-user epic ([EPIC_MULTIUSER.md](../ArchiMateAPI/EPIC_MULTIUSER.md), MU-3 and MU-22) |
| ~~The relationships ArchiMate allows between two element types, as a resource~~ | **Done in 1.2.0** as the tool `allowed_relationships` (MCP-21), on the API's BL-51: the whole table is about 230 KB, too long for a resource an assistant reads |
