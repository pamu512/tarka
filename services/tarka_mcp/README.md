# Tarka MCP (decision context)

Stdio MCP server exposing decision-graph tools.

```bash
export GRAPH_SERVICE_URL=http://127.0.0.1:8082
export DECISION_GRAPH_ENABLED=1
export ALLOW_INSECURE_NO_AUTH=true   # local graph-service
cd /path/to/tarka && PYTHONPATH=services python -m tarka_mcp
```

Cursor MCP config:

```json
{
  "mcpServers": {
    "tarka": {
      "command": "python",
      "args": ["-m", "tarka_mcp"],
      "cwd": "/path/to/tarka",
      "env": {
        "PYTHONPATH": "services",
        "GRAPH_SERVICE_URL": "http://127.0.0.1:8082",
        "DECISION_GRAPH_ENABLED": "1"
      }
    }
  }
}
```

Semantica MCP remains optional (`services/semantica-bridge`); this server is the product plane.
