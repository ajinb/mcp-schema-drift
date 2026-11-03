"""A tiny stdio MCP server for tests: paginated tools/list, optional emptied schemas."""

import json
import sys

EMPTY = "--empty" in sys.argv
TOOLS = [
    {"name": "read_file", "inputSchema": {"type": "object",
     "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "list_dir", "inputSchema": {"type": "object",
     "properties": {"path": {"type": "string"}, "depth": {"type": "integer"}}, "required": ["path"]}},
    {"name": "ping", "inputSchema": {"type": "object", "properties": {}}},
]
if EMPTY:
    TOOLS = [{**t, "inputSchema": {"$schema": "http://json-schema.org/draft-07/schema#"}} for t in TOOLS]

print("server booting (not JSON-RPC, must be skipped)", flush=True)
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    if msg["method"] == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "fake", "version": "0.0.1"}}
    elif msg["method"] == "tools/list":
        page = 1 if msg.get("params", {}).get("cursor") == "p2" else 0
        result = {"tools": TOOLS[:2]} if page == 0 else {"tools": TOOLS[2:]}
        if page == 0:
            result["nextCursor"] = "p2"
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
