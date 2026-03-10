"""MCPServer: exposes PostgreSQL stored functions as MCP tools via JSON-RPC over stdio."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import psycopg

from confiture.core.introspection.functions import FunctionIntrospector
from confiture.core.introspection.type_mapping import TypeMapper
from confiture.models.mcp_models import MCPTool

if TYPE_CHECKING:
    from confiture.models.function_info import FunctionCatalog


_MCP_PROTOCOL_VERSION = "2024-11-05"


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    """Build a JSON-RPC error response."""
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


class MCPServer:
    """Exposes PostgreSQL stored functions as MCP tools via JSON-RPC."""

    def __init__(
        self,
        connection: psycopg.Connection,
        schema: str = "public",
        name_pattern: str | None = None,
    ) -> None:
        self._conn = connection
        self._schema = schema
        self._name_pattern = name_pattern
        self._catalog: FunctionCatalog | None = None
        self._tools: dict[str, MCPTool] = {}
        self._mapper = TypeMapper()
        self._introspector = FunctionIntrospector(connection)

    def initialize(self) -> None:
        """Introspect the database and build the tool registry."""
        self._catalog = self._introspector.introspect(
            self._schema, name_pattern=self._name_pattern
        )
        self._tools = {
            f.name: MCPTool.from_function_info(f, self._mapper) for f in self._catalog.functions
        }

    def list_tools(self) -> list[MCPTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a PostgreSQL function by name with the given arguments."""
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name!r}")
        assert self._catalog is not None
        func_info = next(f for f in self._catalog.functions if f.name == name)
        args = [arguments[p.name] for p in func_info.in_params if p.name in arguments]
        placeholders = ", ".join(["%s"] * len(args))
        if func_info.is_procedure:
            sql = f"CALL {self._schema}.{name}({placeholders})"
        else:
            sql = f"SELECT {self._schema}.{name}({placeholders})"
        with self._conn.cursor() as cur:
            cur.execute(sql, args)
            if func_info.is_procedure:
                return None
            row = cur.fetchone()
            return row[0] if row else None

    def handle_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a single JSON-RPC message and return the response."""
        method = msg.get("method")
        msg_id = msg.get("id")
        try:
            if method == "initialize":
                result: Any = {
                    "protocolVersion": _MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "confiture-mcp", "version": "0.7.2"},
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": t.input_schema,
                        }
                        for t in self.list_tools()
                    ]
                }
            elif method == "tools/call":
                params = msg.get("params", {})
                value = self.call_tool(params["name"], params.get("arguments", {}))
                result = {"content": [{"type": "text", "text": json.dumps(value, default=str)}]}
            elif method == "notifications/initialized":
                return {}
            else:
                return _error(msg_id, -32601, "Method not found")
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as e:
            return _error(msg_id, -32603, str(e))

    def serve_stdio(self) -> None:
        """Run the MCP server, reading JSON-RPC messages from stdin."""
        self.initialize()
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            response = self.handle_message(msg)
            if response:
                print(json.dumps(response), flush=True)  # noqa: T201
