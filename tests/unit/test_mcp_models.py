"""Unit tests for MCP models."""

from __future__ import annotations

from confiture.core.introspection.type_mapping import TypeMapper
from confiture.models.function_info import FunctionInfo, FunctionParam, Volatility
from confiture.models.mcp_models import MCPTool, _pg_to_json_schema_type


def _make_func(
    name: str = "get_user",
    params: list | None = None,
    return_type: str = "text",
) -> FunctionInfo:
    return FunctionInfo(
        schema="public",
        name=name,
        oid=1,
        params=params or [],
        return_type=return_type,
        returns_set=False,
        volatility=Volatility.STABLE,
        is_procedure=False,
        language="sql",
        source=None,
        estimated_cost=1.0,
    )


def test_pg_to_json_schema_type_integer():
    assert _pg_to_json_schema_type("int") == "integer"


def test_pg_to_json_schema_type_string():
    assert _pg_to_json_schema_type("str") == "string"


def test_pg_to_json_schema_type_boolean():
    assert _pg_to_json_schema_type("bool") == "boolean"


def test_pg_to_json_schema_type_array():
    assert _pg_to_json_schema_type("list[str]") == "array"


def test_pg_to_json_schema_type_object():
    assert _pg_to_json_schema_type("dict[str, Any]") == "object"


def test_pg_to_json_schema_type_unknown_defaults_to_string():
    assert _pg_to_json_schema_type("MyCustomType") == "string"


def test_mcp_tool_from_function_info_no_params():
    mapper = TypeMapper()
    func = _make_func(name="hello")
    tool = MCPTool.from_function_info(func, mapper)
    assert tool.name == "hello"
    assert "hello" in tool.description
    assert tool.input_schema["type"] == "object"
    assert tool.input_schema["properties"] == {}
    assert tool.input_schema["required"] == []


def test_mcp_tool_from_function_info_with_params():
    mapper = TypeMapper()
    func = _make_func(
        name="add",
        params=[
            FunctionParam(name="x", pg_type="integer", has_default=False),
            FunctionParam(name="y", pg_type="integer", has_default=True),
        ],
        return_type="integer",
    )
    tool = MCPTool.from_function_info(func, mapper)
    assert "x" in tool.input_schema["properties"]
    assert tool.input_schema["properties"]["x"]["type"] == "integer"
    assert "x" in tool.input_schema["required"]
    assert "y" not in tool.input_schema["required"]  # has default


def test_mcp_tool_description_includes_volatility():
    mapper = TypeMapper()
    func = _make_func()
    tool = MCPTool.from_function_info(func, mapper)
    assert "STABLE" in tool.description
