"""Data models for MCP (Model Context Protocol) server."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from confiture.core.introspection.type_mapping import TypeMapper
    from confiture.models.function_info import FunctionInfo


def _pg_to_json_schema_type(py_type: str) -> str:
    """Map Python type annotation to JSON Schema type."""
    mapping = {
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "str": "string",
        "dict[str, Any]": "object",
        "Any": "string",
        "None": "null",
    }
    if py_type.startswith("list["):
        return "array"
    return mapping.get(py_type, "string")


@dataclasses.dataclass
class MCPTool:
    """A single MCP tool representing a PostgreSQL function."""

    name: str
    description: str
    input_schema: dict[str, Any]

    @classmethod
    def from_function_info(cls, info: FunctionInfo, mapper: TypeMapper) -> MCPTool:
        """Build an MCPTool from FunctionInfo."""
        props: dict[str, Any] = {}
        required: list[str] = []
        for param in info.in_params:
            py_type = mapper.pg_to_python(param.pg_type)
            json_type = _pg_to_json_schema_type(py_type)
            props[param.name] = {
                "type": json_type,
                "description": f"PostgreSQL type: {param.pg_type}",
            }
            if not param.has_default:
                required.append(param.name)
        return cls(
            name=info.name,
            description=f"Call {info.qualified_name} ({info.volatility.value})",
            input_schema={"type": "object", "properties": props, "required": required},
        )
