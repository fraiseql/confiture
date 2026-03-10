"""Map PostgreSQL types to Python type annotations."""

from __future__ import annotations


class TypeMapper:
    """Bidirectional mapping between PostgreSQL and Python types."""

    _DEFAULT: dict[str, str] = {
        # Numeric
        "smallint": "int",
        "integer": "int",
        "bigint": "int",
        "numeric": "Decimal",
        "real": "float",
        "double precision": "float",
        "serial": "int",
        "bigserial": "int",
        # Text
        "text": "str",
        "character varying": "str",
        "char": "str",
        "name": "str",
        # Boolean
        "boolean": "bool",
        # Date/Time
        "date": "date",
        "timestamp without time zone": "datetime",
        "timestamp with time zone": "datetime",
        "time without time zone": "time",
        "time with time zone": "time",
        "interval": "timedelta",
        # JSON
        "json": "dict[str, Any]",
        "jsonb": "dict[str, Any]",
        # UUID
        "uuid": "UUID",
        # Binary
        "bytea": "bytes",
        # Network
        "inet": "str",
        "cidr": "str",
        "macaddr": "str",
        # Geometric
        "point": "str",
        "line": "str",
        "box": "str",
        # Void
        "void": "None",
    }

    _IMPORT_MAP: dict[str, str] = {
        "Decimal": "from decimal import Decimal",
        "date": "from datetime import date",
        "datetime": "from datetime import datetime",
        "time": "from datetime import time",
        "timedelta": "from datetime import timedelta",
        "dict[str, Any]": "from typing import Any",
        "UUID": "from uuid import UUID",
    }

    def __init__(self, custom_mappings: dict[str, str] | None = None) -> None:
        self._mappings = {**self._DEFAULT, **(custom_mappings or {})}

    def pg_to_python(self, pg_type: str) -> str:
        """Map a PostgreSQL type string to a Python type annotation.

        Handles:
        - Exact matches (e.g. "bigint" -> "int")
        - Parameterized types (e.g. "character varying(255)" -> "str")
        - Array types (e.g. "integer[]" -> "list[int]")
        - Unknown types fall back to "Any"
        """
        # Handle array types
        if pg_type.endswith("[]"):
            base = pg_type[:-2].strip()
            base_py = self.pg_to_python(base)
            return f"list[{base_py}]"

        # Strip parameterization: "character varying(255)" -> "character varying"
        base_type = pg_type.split("(")[0].strip()

        # Direct lookup
        if base_type in self._mappings:
            return self._mappings[base_type]

        # Exact pg_type lookup (with params)
        if pg_type in self._mappings:
            return self._mappings[pg_type]

        return "Any"

    def python_imports(self, pg_types: list[str]) -> set[str]:
        """Return the set of Python import statements needed for the given PG types."""
        imports: set[str] = set()
        py_types = {self.pg_to_python(t) for t in pg_types}

        for py_type in py_types:
            if py_type == "Any":
                imports.add("from typing import Any")
            elif py_type in self._IMPORT_MAP:
                imports.add(self._IMPORT_MAP[py_type])
            elif py_type.startswith("list["):
                inner = py_type[5:-1]
                if inner in self._IMPORT_MAP:
                    imports.add(self._IMPORT_MAP[inner])
                if inner == "Any" or py_type == "list[Any]":
                    imports.add("from typing import Any")

        return imports
