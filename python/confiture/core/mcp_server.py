"""MCPServer: exposes Confiture operations and PostgreSQL functions as MCP tools.

Built-in tools (``confiture__*`` prefix):
- ``confiture__migrate_status``  — pending / applied migration list
- ``confiture__migrate_up``      — apply pending migrations
- ``confiture__migrate_down``    — roll back N migrations
- ``confiture__schema_introspect`` — table / column / FK discovery
- ``confiture__drift_check``     — live DB vs DDL drift detection

PostgreSQL stored functions are also exposed automatically, each under a tool
name no other tool holds: a routine whose name a built-in or another routine's
tool already holds is listed as ``<name>__<oid>``.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg import sql

from confiture import __version__
from confiture.core import migrator as _core_migrator
from confiture.core.connection import require_mode
from confiture.core.drift import SchemaDriftDetector
from confiture.core.introspection.functions import FunctionIntrospector
from confiture.core.introspection.tables import SchemaIntrospector
from confiture.core.introspection.type_mapping import TypeMapper
from confiture.models.mcp_models import MCPTool

if TYPE_CHECKING:
    from confiture.models.function_info import FunctionCatalog, FunctionInfo


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


#: What many MCP clients accept as a tool name's length.
_TOOL_NAME_LIMIT = 64


def _tool_names(functions: list[FunctionInfo]) -> dict[str, FunctionInfo]:
    """Each routine under one tool name that no other tool holds.

    A name one routine holds is its tool's name, unchanged. The overloads of one
    name are one tool each, ``f__integer`` and ``f__text``, spelled from their
    input types with everything but ``[a-z0-9_]`` made ``_`` — and, past what a
    client accepts, ``f__<oid>``. A name two routines would share, or a built-in
    holds (a routine named ``confiture__migrate_down``), is ``<name>__<oid>`` for
    every routine that wanted it, whatever order the catalogue lists them in: a
    call by a name reaches exactly one thing.
    """
    by_name: dict[str, list[FunctionInfo]] = {}
    for info in functions:
        by_name.setdefault(info.name, []).append(info)
    wanted: list[tuple[str, FunctionInfo]] = []
    for name, overloads in by_name.items():
        if len(overloads) == 1:
            wanted.append((name, overloads[0]))
            continue
        for info in overloads:
            types = "_".join(p.pg_type for p in info.in_params) or "noargs"
            tool = f"{name}__{re.sub(r'[^a-z0-9_]', '_', types.lower())}"
            wanted.append((tool if len(tool) <= _TOOL_NAME_LIMIT else f"{name}__{info.oid}", info))
    claims = Counter(tool for tool, _ in wanted)
    taken = {tool["name"] for tool in _BUILTIN_TOOLS}
    tools: dict[str, FunctionInfo] = {}
    for tool, info in wanted:
        name = f"{info.name}__{info.oid}" if claims[tool] > 1 or tool in taken else tool
        # An oid name another routine holds outright: the oid is unique, so a suffix is too.
        while name in tools or (name != tool and name in claims):
            name += "_"
        tools[name] = info
    return tools


class MCPServer:
    """Exposes Confiture operations and PostgreSQL stored functions as MCP tools.

    Built-in ``confiture__*`` tools give agents direct programmatic access to
    migration control, schema introspection, and drift detection without
    shelling out to the CLI.

    PostgreSQL stored functions in the target schema are also discovered
    automatically and registered as additional tools.

    **A tool call is one statement** (#373): committed when it returns, rolled back
    when it raises, its locks released either way. The connection must therefore be
    in autocommit. :meth:`from_url` opens one so, and owns it — after a
    connection-level error it reconnects for the next call. A connection a caller
    hands in is never switched: one in a transaction is refused.

    Args:
        connection: An open psycopg connection to the target database, in autocommit.
        schema: PostgreSQL schema to introspect for stored functions.
        name_pattern: Optional SQL LIKE pattern to filter function names.
        expose_confiture_tools: Register built-in Confiture tools (default: True).

    Raises:
        ConfigurationError: ``CONFIG_013`` when *connection* is not in autocommit.
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        schema: str = "public",
        name_pattern: str | None = None,
        expose_confiture_tools: bool = True,
    ) -> None:
        require_mode(
            connection,
            autocommit=True,
            call="MCPServer",
            reason="each tool call is one statement, committed when it returns and "
            "rolled back when it raises; in a transaction its writes and locks would "
            "outlive it, and one error would fail every call after it",
        )
        self._url: str | None = None
        self._conn = connection
        self._schema = schema
        self._name_pattern = name_pattern
        self._expose_confiture_tools = expose_confiture_tools
        self._catalog: FunctionCatalog | None = None
        self._pg_tools: dict[str, MCPTool] = {}
        self._routines: dict[str, FunctionInfo] = {}
        self._mapper = TypeMapper()
        self._introspector = FunctionIntrospector(connection)

    @classmethod
    def from_url(
        cls,
        database_url: str,
        schema: str = "public",
        name_pattern: str | None = None,
        expose_confiture_tools: bool = True,
    ) -> MCPServer:
        """A server on a connection it opens to *database_url*, in autocommit, and owns."""
        server = cls(
            psycopg.connect(database_url, autocommit=True),
            schema=schema,
            name_pattern=name_pattern,
            expose_confiture_tools=expose_confiture_tools,
        )
        server._url = database_url
        return server

    def close(self) -> None:
        """Close the connection :meth:`from_url` opened; a caller's is the caller's to close."""
        if self._url is not None:
            self._conn.close()

    def _reconnect(self) -> None:
        """Replace a connection this server owns once PostgreSQL has lost it."""
        if self._url is None:
            return
        self._conn.close()
        self._conn = psycopg.connect(self._url, autocommit=True)
        self._introspector = FunctionIntrospector(self._conn)

    def initialize(self) -> None:
        """Introspect the database and build the tool registry."""
        self._catalog = self._introspector.introspect(self._schema, name_pattern=self._name_pattern)
        self._routines = _tool_names(self._catalog.functions)
        self._pg_tools = {
            tool: replace(MCPTool.from_function_info(info, self._mapper), name=tool)
            for tool, info in self._routines.items()
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

        config_path = Path(arguments["config_path"])
        with _core_migrator.Migrator.from_config(config_path) as session:
            result = session.status()
        return result.to_dict()

    def _call_migrate_up(self, arguments: dict[str, Any]) -> dict[str, Any]:

        config_path = Path(arguments["config_path"])
        target: str | None = arguments.get("target")
        dry_run: bool = bool(arguments.get("dry_run", False))
        with _core_migrator.Migrator.from_config(config_path) as session:
            result = session.up(target=target, dry_run=dry_run)
        return result.to_dict()

    def _call_migrate_down(self, arguments: dict[str, Any]) -> dict[str, Any]:

        config_path = Path(arguments["config_path"])
        steps: int = int(arguments.get("steps", 1))
        dry_run: bool = bool(arguments.get("dry_run", False))
        with _core_migrator.Migrator.from_config(config_path) as session:
            result = session.down(steps=steps, dry_run=dry_run)
        return result.to_dict()

    def _call_schema_introspect(self, arguments: dict[str, Any]) -> dict[str, Any]:

        schema: str = arguments.get("schema", "public")
        all_tables: bool = bool(arguments.get("all_tables", False))
        result = SchemaIntrospector(self._conn).introspect(schema=schema, all_tables=all_tables)
        return result.to_dict()

    def _call_drift_check(self, arguments: dict[str, Any]) -> dict[str, Any]:

        schema_file: str = arguments.get("schema_file", "db/generated/schema_local.sql")
        detector = SchemaDriftDetector(self._conn)
        report = detector.compare_with_schema_file(schema_file)
        return report.to_dict()

    # ── PostgreSQL function dispatch ──────────────────────────────────────────

    def _call_pg_function(self, name: str, arguments: dict[str, Any]) -> Any:
        func_info = self._routines.get(name)
        if func_info is None:
            raise ValueError(f"Unknown tool: {name!r}")
        given = [p for p in func_info.in_params if p.name in arguments]
        args = [arguments[p.name] for p in given]
        # The schema and the routine's name are identifiers, quoted whatever they
        # hold: the name is pg_proc's and the schema the caller's. A raw cursor
        # binds `$n` server-side and reads no `%` in the text, so a `%` in a name
        # is only ever part of the name (#375).
        # Each argument is cast to the type its parameter declares, so PostgreSQL
        # resolves exactly this overload and never a sibling of the same name.
        placeholders = sql.SQL(", ").join(
            sql.SQL(f"${i}::{p.pg_type}") for i, p in enumerate(given, start=1)
        )
        statement = sql.SQL("CALL {}({})" if func_info.is_procedure else "SELECT {}({})").format(
            sql.Identifier(self._schema, func_info.name), placeholders
        )
        with psycopg.RawCursor(self._conn) as cur:
            cur.execute(statement, args)
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
        try:
            if name in dispatch and self._expose_confiture_tools:
                return dispatch[name](arguments)
            return self._call_pg_function(name, arguments)
        except psycopg.OperationalError:
            # The call's outcome is unknown, not failed; the next call gets a live connection.
            if self._conn.closed or self._conn.broken:
                self._reconnect()
            raise

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
                    "serverInfo": {"name": "confiture-mcp", "version": __version__},
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
        except Exception as e:  # Reason: a JSON-RPC server answers every failure with an error response; nothing may escape the dispatch
            return _error(msg_id, -32603, str(e))

    def serve_stdio(self) -> None:
        """Run the MCP server, reading JSON-RPC messages from stdin."""
        self.initialize()
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            response = self.handle_message(msg)
            if response:
                print(json.dumps(response), flush=True)
