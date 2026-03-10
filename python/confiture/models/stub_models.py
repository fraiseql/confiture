"""Data models for Python stub generation from PostgreSQL functions."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from confiture.core.introspection.type_mapping import TypeMapper
    from confiture.models.function_info import FunctionInfo


def _to_pascal_case(name: str) -> str:
    """Convert snake_case to PascalCase."""
    return "".join(word.capitalize() for word in name.split("_"))


def _build_pydantic_model(name: str, keys: list, mapper: TypeMapper) -> str:
    """Generate Pydantic model source for JSONB return type."""
    lines = [f"class {name}(BaseModel):", f'    """JSONB return type for {name}."""']
    for key in keys:
        py_type = mapper.pg_to_python(key.inferred_type) if key.inferred_type else "Any"
        lines.append(f"    {key.key}: {py_type}")
    return "\n".join(lines)


@dataclasses.dataclass
class StubFunction:
    """A single Python wrapper function generated from a PostgreSQL function."""

    name: str
    schema: str
    qualified_name: str
    python_params: list[tuple[str, str]]  # (name, py_type)
    python_return: str
    is_procedure: bool
    volatility: str
    language: str
    pydantic_model: str | None  # class source if return is JSONB with inferred shape
    pydantic_model_name: str | None  # class name only
    docstring: str
    required_imports: set[str]

    @classmethod
    def _extract_jsonb_keys(cls, source: str) -> list:
        """Extract JSONB keys from function source using regex (no pglast required)."""
        import re

        from confiture.core.introspection.sql_ast import JSONBKey

        keys: list = []
        pattern = re.compile(r"jsonb_build_object\s*\((.*?)\)", re.DOTALL | re.IGNORECASE)
        for match in pattern.finditer(source):
            args_text = match.group(1)
            args = [a.strip() for a in args_text.split(",")]
            for i in range(0, len(args) - 1, 2):
                key_expr = args[i].strip("'\" ")
                value_expr = args[i + 1].strip() if i + 1 < len(args) else ""
                keys.append(JSONBKey(key=key_expr, value_expr=value_expr))
        return keys

    @classmethod
    def from_function_info(cls, info: FunctionInfo, mapper: TypeMapper) -> StubFunction:
        """Build a StubFunction from FunctionInfo."""
        python_params = [
            (p.name or f"arg{i}", mapper.pg_to_python(p.pg_type))
            for i, p in enumerate(info.in_params)
        ]

        # Collect imports for param types
        imports: set[str] = set()
        param_pg_types = [p.pg_type for p in info.in_params]
        imports.update(mapper.python_imports(param_pg_types))

        pydantic_model = None
        pydantic_model_name = None

        if info.return_type and "jsonb" in info.return_type.lower() and info.source:
            keys = cls._extract_jsonb_keys(info.source)
            if keys:
                model_name = _to_pascal_case(info.name) + "Result"
                pydantic_model = _build_pydantic_model(model_name, keys, mapper)
                pydantic_model_name = model_name
                python_return = model_name
                imports.add("from pydantic import BaseModel")
            else:
                python_return = "dict[str, Any]"
                imports.add("from typing import Any")
        elif info.return_type:
            python_return = mapper.pg_to_python(info.return_type)
            imports.update(mapper.python_imports([info.return_type]))
        else:
            python_return = "None"

        imports.add("import psycopg")

        docstring = (
            f"Call {info.qualified_name} stored {'procedure' if info.is_procedure else 'function'}.\n\n"
            f"    Volatility: {info.volatility.value}  Language: {info.language}"
        )

        return cls(
            name=info.name,
            schema=info.schema,
            qualified_name=info.qualified_name,
            python_params=python_params,
            python_return=python_return,
            is_procedure=info.is_procedure,
            volatility=info.volatility.value,
            language=info.language,
            pydantic_model=pydantic_model,
            pydantic_model_name=pydantic_model_name,
            docstring=docstring,
            required_imports=imports,
        )

    def render_function(self, *, async_mode: bool = False) -> str:
        """Render the function as Python source code."""
        conn_type = "psycopg.AsyncConnection" if async_mode else "psycopg.Connection"
        async_kw = "async " if async_mode else ""
        await_kw = "await " if async_mode else ""

        param_lines = [f"    conn: {conn_type}"]
        for name, py_type in self.python_params:
            param_lines.append(f"    {name}: {py_type}")

        placeholders = ", ".join(["%s"] * len(self.python_params))
        arg_names = [name for name, _ in self.python_params]
        arg_list = ", ".join(arg_names)

        if self.is_procedure:
            sql = f"CALL {self.qualified_name}({placeholders})"
        else:
            sql = f"SELECT {self.qualified_name}({placeholders})"

        if len(arg_names) == 1:
            args_tuple = f"({arg_names[0]},)"
        elif arg_names:
            args_tuple = f"({arg_list},)"
        else:
            args_tuple = "()"

        lines = [
            f"{async_kw}def {self.name}(",
            *[line + "," for line in param_lines],
            f") -> {self.python_return}:",
            f'    """{self.docstring}"""',
            f"    {async_kw}with conn.cursor() as cur:",
            f"        {await_kw}cur.execute(",
            f'            "{sql}",',
            f"            {args_tuple},",
            "        )",
        ]

        if self.pydantic_model_name:
            lines.append(f"        row = {await_kw}cur.fetchone()")
            lines.append(f"        return {self.pydantic_model_name}.model_validate(row[0])")
        elif self.is_procedure:
            lines.append("        return None")
        else:
            lines.append(f"        row = {await_kw}cur.fetchone()")
            lines.append("        return row[0] if row else None")

        return "\n".join(lines)


@dataclasses.dataclass
class StubFile:
    """A generated Python file containing function stubs."""

    schema: str
    database: str
    generated_at: str
    functions: list[StubFunction]
    imports: set[str]

    def render(self, output_format: str = "pydantic") -> str:  # noqa: ARG002
        """Render to Python source code."""
        header_lines = [
            "# Generated by confiture generate stubs",
            f"# Schema: {self.schema}  Database: {self.database}  Generated: {self.generated_at}",
            "# DO NOT EDIT — regenerate with: confiture generate stubs ...",
            "",
            "from __future__ import annotations",
        ]

        # Collect all imports
        all_imports: set[str] = set(self.imports)
        for fn in self.functions:
            all_imports.update(fn.required_imports)

        # Sort imports
        sorted_imports = sorted(all_imports)
        header_lines.extend(sorted_imports)
        header_lines.append("")
        header_lines.append("")

        sections: list[str] = []

        # Add pydantic models first
        for fn in self.functions:
            if fn.pydantic_model:
                sections.append(fn.pydantic_model)
                sections.append("")
                sections.append("")

        # Add function stubs
        for fn in self.functions:
            sections.append(fn.render_function())
            sections.append("")
            sections.append("")

        return "\n".join(header_lines) + "\n".join(sections)
