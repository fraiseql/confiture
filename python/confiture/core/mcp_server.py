"""MCPServer: exposes Confiture operations and PostgreSQL functions as MCP tools.

Built-in tools (``confiture__*`` prefix):
- ``confiture__migrate_status``  — pending / applied migration list
- ``confiture__migrate_up``      — apply pending migrations
- ``confiture__migrate_down``    — roll back N migrations
- ``confiture__schema_introspect`` — table / column / FK discovery
- ``confiture__drift_check``     — live DB vs DDL drift detection

PostgreSQL stored functions are also exposed automatically; their names
come directly from the database so they will never collide with the
``confiture__`` prefix.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg

from confiture.core.introspection.functions import FunctionIntrospector
from confiture.core.introspection.type_mapping import TypeMapper
from confiture.models.mcp_models import MCPTool

if TYPE_CHECKING:
    from confiture.models.function_info import FunctionCatalog


_MCP_PROTOCOL_VERSION = "2024-11-05"

# ── JSON Schema fragments used by built-in tools ──────────────────────────────

_CONFIG_PATH_PROP = {
    "config_path": {
        "type": "string",
        "description": "Path to confiture YAML config (e.g. db/environments/local.yaml)",
    }
}

_BUILTIN_TOOLS: list[dict[str, Any]] = [
    {
        "name": "confiture__migrate_status",
        "description": (
            "Return migration status: list of applied and pending migrations "
            "with versions, names, and checksums."
        ),
        "inputSchema": {
            "type": "object",
            "properties": _CONFIG_PATH_PROP,
            "required": ["config_path"],
        },
    },
    {
        "name": "confiture__migrate_up",
        "description": (
            "Apply pending migrations up to an optional target version. "
            "Returns applied migration names, durations, and any errors."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_CONFIG_PATH_PROP,
                "target": {
                    "type": "string",
                    "description": "Stop after applying this version (optional).",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Simulate without writing (default: false).",
                    "default": False,
                },
            },
            "required": ["config_path"],
        },
    },
    {
        "name": "confiture__migrate_down",
        "description": "Roll back the last N migrations. Returns rolled-back migration names.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_CONFIG_PATH_PROP,
                "steps": {
                    "type": "integer",
                    "description": "Number of migrations to roll back (default: 1).",
                    "default": 1,
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Simulate without writing (default: false).",
                    "default": False,
                },
            },
            "required": ["config_path"],
        },
    },
    {
        "name": "confiture__schema_introspect",
        "description": (
            "Introspect tables, columns, types, and foreign-key relationships "
            "in the connected database. Uses the server's existing connection."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schema": {
                    "type": "string",
                    "description": "PostgreSQL schema to introspect (default: public).",
                    "default": "public",
                },
                "all_tables": {
                    "type": "boolean",
                    "description": "Include all tables, not only tb_-prefixed (default: false).",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "confiture__drift_check",
        "description": (
            "Compare the live database schema against a generated schema SQL file and "
            "report any drift (added/removed/changed tables and columns)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schema_file": {
                    "type": "string",
                    "description": (
                        "Path to the generated schema SQL file to compare against "
                        "(default: db/generated/schema_local.sql). "
                        "Generate it first with: confiture build"
                    ),
                    "default": "db/generated/schema_local.sql",
                },
            },
        },
    },
]


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    """Build a JSON-RPC error response."""
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


class MCPServer:
    """Exposes Confiture operations and PostgreSQL stored functions as MCP tools.

    Built-in ``confiture__*`` tools give agents direct programmatic access to
    migration control, schema introspection, and drift detection without
    shelling out to the CLI.

    PostgreSQL stored functions in the target schema are also discovered
    automatically and registered as additional tools.

    Args:
        connection: An open psycopg connection to the target database.
        schema: PostgreSQL schema to introspect for stored functions.
        name_pattern: Optional SQL LIKE pattern to filter function names.
        expose_confiture_tools: Register built-in Confiture tools (default: True).
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        schema: str = "public",
        name_pattern: str | None = None,
        expose_confiture_tools: bool = True,
    ) -> None:
        self._conn = connection
        self._schema = schema
        self._name_pattern = name_pattern
        self._expose_confiture_tools = expose_confiture_tools
        self._catalog: FunctionCatalog | None = None
        self._pg_tools: dict[str, MCPTool] = {}
        self._mapper = TypeMapper()
        self._introspector = FunctionIntrospector(connection)

    def initialize(self) -> None:
        """Introspect the database and build the tool registry."""
        self._catalog = self._introspector.introspect(self._schema, name_pattern=self._name_pattern)
        self._pg_tools = {
            f.name: MCPTool.from_function_info(f, self._mapper) for f in self._catalog.functions
        }

    def list_tools(self) -> list[dict[str, Any]]:
        """Return all registered tools as JSON-Schema dicts."""
        tools: list[dict[str, Any]] = []
        if self._expose_confiture_tools:
            tools.extend(_BUILTIN_TOOLS)
        tools.extend(
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in self._pg_tools.values()
        )
        return tools

    # ── Built-in Confiture tool dispatch ─────────────────────────────────────

    def _call_migrate_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from confiture.core.migrator import Migrator

        config_path = Path(arguments["config_path"])
        with Migrator.from_config(config_path) as session:
            result = session.status()
        return result.to_dict()

    def _call_migrate_up(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from confiture.core.migrator import Migrator

        config_path = Path(arguments["config_path"])
        target: str | None = arguments.get("target")
        dry_run: bool = bool(arguments.get("dry_run", False))
        with Migrator.from_config(config_path) as session:
            result = session.up(target=target, dry_run=dry_run)
        return result.to_dict()

    def _call_migrate_down(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from confiture.core.migrator import Migrator

        config_path = Path(arguments["config_path"])
        steps: int = int(arguments.get("steps", 1))
        dry_run: bool = bool(arguments.get("dry_run", False))
        with Migrator.from_config(config_path) as session:
            result = session.down(steps=steps, dry_run=dry_run)
        return result.to_dict()

    def _call_schema_introspect(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from confiture.core.introspector import SchemaIntrospector

        schema: str = arguments.get("schema", "public")
        all_tables: bool = bool(arguments.get("all_tables", False))
        result = SchemaIntrospector(self._conn).introspect(schema=schema, all_tables=all_tables)
        return result.to_dict()

    def _call_drift_check(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from confiture.core.drift import SchemaDriftDetector

        schema_file: str = arguments.get("schema_file", "db/generated/schema_local.sql")
        detector = SchemaDriftDetector(self._conn)
        report = detector.compare_with_schema_file(schema_file)
        return report.to_dict()

    # ── PostgreSQL function dispatch ──────────────────────────────────────────

    def _call_pg_function(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self._pg_tools:
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

    # ── Unified call_tool ─────────────────────────────────────────────────────

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Dispatch a tool call to a built-in Confiture tool or a PostgreSQL function."""
        dispatch = {
            "confiture__migrate_status": self._call_migrate_status,
            "confiture__migrate_up": self._call_migrate_up,
            "confiture__migrate_down": self._call_migrate_down,
            "confiture__schema_introspect": self._call_schema_introspect,
            "confiture__drift_check": self._call_drift_check,
        }
        if name in dispatch:
            return dispatch[name](arguments)
        return self._call_pg_function(name, arguments)

    # ── JSON-RPC message handling ─────────────────────────────────────────────

    def handle_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a single JSON-RPC message and return the response."""
        method = msg.get("method")
        msg_id = msg.get("id")
        try:
            if method == "initialize":
                result: Any = {
                    "protocolVersion": _MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "confiture-mcp", "version": "0.8.0"},
                }
            elif method == "tools/list":
                result = {"tools": self.list_tools()}
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
