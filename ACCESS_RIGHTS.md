# Access rights

The guide to keys, roles and access rights of the ArchiMate tools is in the
ArchiMate API's folder: [../ArchiMateAPI/ACCESS_RIGHTS.md](../ArchiMateAPI/ACCESS_RIGHTS.md).

For the MCP server, in short: over stdio it uses the API key `API_KEY` of
its `.env`; on your own machine, put your own key there, and the API's
record of changes names you. Over HTTP either every client sends its own
API key (`CLIENT_KEYS=true`, 1.7.0), or all clients send the server's
`MCP_TOKEN` and work with its `API_KEY`. A `reader` key is enough for every
reading tool; `model_history` needs `editor`; the write tools need `editor`
and `ALLOW_WRITE=true`; `create_model` and `update_model` need `admin`.
See *The ArchiMate MCP server* and the recipes in the guide.
