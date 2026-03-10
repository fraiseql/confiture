"""Tests for AX (Agent Experience) public API completeness."""

import confiture


def test_schema_introspector_importable():
    """SchemaIntrospector is importable from the top-level package."""
    from confiture import SchemaIntrospector  # noqa: F401

    assert "SchemaIntrospector" in confiture.__all__


def test_introspection_models_importable():
    """IntrospectionResult, IntrospectedTable, IntrospectedColumn, FKReference are in __all__."""
    from confiture import (  # noqa: F401
        FKReference,
        IntrospectedColumn,
        IntrospectedTable,
        IntrospectionResult,
    )

    for name in ("IntrospectionResult", "IntrospectedTable", "IntrospectedColumn", "FKReference"):
        assert name in confiture.__all__, f"{name} missing from __all__"


def test_seed_applier_importable():
    """SeedApplier and ApplyResult are importable from the top-level package."""
    from confiture import ApplyResult, SeedApplier  # noqa: F401

    assert "SeedApplier" in confiture.__all__
    assert "ApplyResult" in confiture.__all__


def test_apply_result_to_dict():
    """ApplyResult.to_dict() returns a dict with expected keys."""
    from confiture import ApplyResult

    r = ApplyResult(total=5, succeeded=4, failed=1, failed_files=["bad.sql"])
    d = r.to_dict()
    assert d["total"] == 5
    assert d["succeeded"] == 4
    assert d["failed"] == 1
    assert d["failed_files"] == ["bad.sql"]
    assert d["success"] is False


def test_mcp_server_exposes_confiture_tools():
    """MCPServer built-in tools list includes confiture__ prefixed tools."""
    from unittest.mock import MagicMock

    from confiture.core.mcp_server import _BUILTIN_TOOLS, MCPServer

    conn = MagicMock()
    server = MCPServer(conn, expose_confiture_tools=True)
    # Must initialise for list_tools() to work (pg tools come from DB introspection)
    server._pg_tools = {}  # skip DB call
    tools = server.list_tools()
    names = {t["name"] for t in tools}
    expected = {t["name"] for t in _BUILTIN_TOOLS}
    assert expected.issubset(names)


def test_mcp_server_can_disable_confiture_tools():
    """expose_confiture_tools=False omits confiture__ tools."""
    from unittest.mock import MagicMock

    from confiture.core.mcp_server import MCPServer

    conn = MagicMock()
    server = MCPServer(conn, expose_confiture_tools=False)
    server._pg_tools = {}
    tools = server.list_tools()
    assert all(not t["name"].startswith("confiture__") for t in tools)


def test_mcp_server_version_matches_package():
    """MCPServer reports the same version as confiture.__version__."""
    from unittest.mock import MagicMock

    from confiture.core.mcp_server import MCPServer

    conn = MagicMock()
    server = MCPServer(conn)
    server._pg_tools = {}
    msg = {"method": "initialize", "id": 1}
    response = server.handle_message(msg)
    assert response["result"]["serverInfo"]["version"] == confiture.__version__


def test_builtin_tools_have_valid_json_schema():
    """Every built-in tool has a valid JSON Schema (type=object, description present)."""
    from confiture.core.mcp_server import _BUILTIN_TOOLS

    for tool in _BUILTIN_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


def test_intent_registry_importable():
    """IntentRegistry is importable from the top-level package."""
    from confiture import IntentRegistry  # noqa: F401

    assert "IntentRegistry" in confiture.__all__


def test_conflict_severity_importable():
    """ConflictSeverity is importable from the top-level package."""
    from confiture import ConflictSeverity  # noqa: F401

    assert "ConflictSeverity" in confiture.__all__


def test_intent_status_importable():
    """IntentStatus is importable from the top-level package."""
    from confiture import IntentStatus  # noqa: F401

    assert "IntentStatus" in confiture.__all__


def test_intent_registry_is_class():
    """IntentRegistry is a proper class that can be instantiated with a connection."""
    from confiture import IntentRegistry

    assert isinstance(IntentRegistry, type)
