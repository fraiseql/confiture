"""Data models for Python stub generation from PostgreSQL functions."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from confiture.core.introspection.type_mapping import TypeMapper
    from confiture.models.function_info import FunctionInfo
    from confiture.models.introspection import JSONBKey


def _to_pascal_case(name: str) -> str:
    """Convert snake_case to PascalCase."""
    return "".join(word.capitalize() for word in name.split("_"))


class StubFormat(StrEnum):
    """What a JSONB result's inferred shape is written as."""

    PYDANTIC = "pydantic"
    DATACLASS = "dataclass"
    TYPEDDICT = "typeddict"


#: Per format: the import it needs, how its class opens, and how a row becomes one.
_MODEL_IMPORT = {
    StubFormat.PYDANTIC: "from pydantic import BaseModel",
    StubFormat.DATACLASS: "import dataclasses",
    StubFormat.TYPEDDICT: "from typing import TypedDict",
}
_MODEL_HEADER = {
    StubFormat.PYDANTIC: "class {name}(BaseModel):",
    StubFormat.DATACLASS: "@dataclasses.dataclass\nclass {name}:",
    StubFormat.TYPEDDICT: "class {name}(TypedDict):",
}
_MODEL_FROM_ROW = {
    StubFormat.PYDANTIC: "{name}.model_validate(row[0])",
    StubFormat.DATACLASS: "{name}(**row[0])",
    StubFormat.TYPEDDICT: "{name}(**row[0])",
}


def _field_type(key: JSONBKey, mapper: TypeMapper) -> str:
    return mapper.pg_to_python(key.inferred_type) if key.inferred_type else "Any"


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
    #: The class a JSONB result with an inferred shape is returned as, and its fields
    #: as ``(name, Python type)``; ``None`` and ``()`` for every other result.
    result_model: str | None
    result_fields: tuple[tuple[str, str], ...]
    docstring: str
    required_imports: set[str]

    def render_model(self, output_format: StubFormat) -> str | None:
        """The result's class in *output_format*, or ``None`` when it has none."""
        if self.result_model is None:
            return None
        lines = [
            _MODEL_HEADER[output_format].format(name=self.result_model),
            f'    """JSONB return type for {self.result_model}."""',
            *(f"    {field}: {py_type}" for field, py_type in self.result_fields),
        ]
        return "\n".join(lines)

    @classmethod
    def from_function_info(
        cls, info: FunctionInfo, mapper: TypeMapper, keys: Sequence[JSONBKey] = ()
    ) -> StubFunction:
        """Build a StubFunction from FunctionInfo.

        *keys* are the fields of the object a JSONB result is built as, read from
        the body by ``stub_generator.jsonb_keys``; none, and the result is a dict.
        """
        python_params = [
            (p.name or f"arg{i}", mapper.pg_to_python(p.pg_type))
            for i, p in enumerate(info.in_params)
        ]

        # Collect imports for param types
        imports: set[str] = set()
        param_pg_types = [p.pg_type for p in info.in_params]
        imports.update(mapper.python_imports(param_pg_types))

        result_model = None
        result_fields: tuple[tuple[str, str], ...] = ()

        if info.return_type and "jsonb" in info.return_type.lower():
            if keys:
                result_model = _to_pascal_case(info.name) + "Result"
                result_fields = tuple((key.key, _field_type(key, mapper)) for key in keys)
                python_return = result_model
                # The imports the annotations use: `Any` is one when a key's type is unknown.
                imports.update(
                    mapper.python_imports([k.inferred_type for k in keys if k.inferred_type])
                )
                if any(py_type == "Any" for _, py_type in result_fields):
                    imports.add("from typing import Any")
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
            result_model=result_model,
            result_fields=result_fields,
            docstring=docstring,
            required_imports=imports,
        )

    def render_function(
        self, *, async_mode: bool = False, output_format: StubFormat = StubFormat.PYDANTIC
    ) -> str:
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

        if self.result_model:
            from_row = _MODEL_FROM_ROW[output_format].format(name=self.result_model)
            lines.append(f"        row = {await_kw}cur.fetchone()")
            lines.append(f"        return {from_row}")
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

    def render(self, output_format: StubFormat | str = StubFormat.PYDANTIC) -> str:
        """Render to Python source code, a JSONB result's class in *output_format*.

        Raises:
            ValueError: *output_format* is not a :class:`StubFormat`.
        """
        output_format = StubFormat(output_format)
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
            if fn.result_model:
                all_imports.add(_MODEL_IMPORT[output_format])

        # Sort imports
        sorted_imports = sorted(all_imports)
        header_lines.extend(sorted_imports)
        header_lines.append("")
        header_lines.append("")

        sections: list[str] = []

        # The result classes first: the functions return them.
        for fn in self.functions:
            if (model := fn.render_model(output_format)) is not None:
                sections.append(model)
                sections.append("")
                sections.append("")

        for fn in self.functions:
            sections.append(fn.render_function(output_format=output_format))
            sections.append("")
            sections.append("")

        return "\n".join(header_lines) + "\n".join(sections)
