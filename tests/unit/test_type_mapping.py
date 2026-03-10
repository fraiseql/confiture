"""Unit tests for TypeMapper: pg_to_python() and python_imports()."""

import pytest

from confiture.core.introspection.type_mapping import TypeMapper


class TestPgToPython:
    def setup_method(self):
        self.mapper = TypeMapper()

    @pytest.mark.parametrize(
        "pg_type,expected",
        [
            ("smallint", "int"),
            ("integer", "int"),
            ("bigint", "int"),
            ("numeric", "Decimal"),
            ("real", "float"),
            ("double precision", "float"),
            ("serial", "int"),
            ("bigserial", "int"),
            ("text", "str"),
            ("character varying", "str"),
            ("char", "str"),
            ("name", "str"),
            ("boolean", "bool"),
            ("date", "date"),
            ("timestamp without time zone", "datetime"),
            ("timestamp with time zone", "datetime"),
            ("time without time zone", "time"),
            ("time with time zone", "time"),
            ("interval", "timedelta"),
            ("json", "dict[str, Any]"),
            ("jsonb", "dict[str, Any]"),
            ("uuid", "UUID"),
            ("bytea", "bytes"),
            ("inet", "str"),
            ("cidr", "str"),
            ("macaddr", "str"),
            ("point", "str"),
            ("line", "str"),
            ("box", "str"),
            ("void", "None"),
        ],
    )
    def test_common_types(self, pg_type: str, expected: str):
        assert self.mapper.pg_to_python(pg_type) == expected

    def test_parameterized_varchar(self):
        assert self.mapper.pg_to_python("character varying(255)") == "str"

    def test_parameterized_numeric(self):
        assert self.mapper.pg_to_python("numeric(10,2)") == "Decimal"

    def test_parameterized_char(self):
        assert self.mapper.pg_to_python("char(3)") == "str"

    def test_array_integer(self):
        assert self.mapper.pg_to_python("integer[]") == "list[int]"

    def test_array_text(self):
        assert self.mapper.pg_to_python("text[]") == "list[str]"

    def test_array_uuid(self):
        assert self.mapper.pg_to_python("uuid[]") == "list[UUID]"

    def test_array_unknown(self):
        assert self.mapper.pg_to_python("mytype[]") == "list[Any]"

    def test_array_jsonb(self):
        assert self.mapper.pg_to_python("jsonb[]") == "list[dict[str, Any]]"

    def test_unknown_type_falls_back_to_any(self):
        assert self.mapper.pg_to_python("myschema.custom_type") == "Any"

    def test_unknown_simple_type(self):
        assert self.mapper.pg_to_python("point3d") == "Any"

    def test_custom_mapping(self):
        mapper = TypeMapper(custom_mappings={"ltree": "str"})
        assert mapper.pg_to_python("ltree") == "str"

    def test_custom_mapping_overrides_default(self):
        mapper = TypeMapper(custom_mappings={"integer": "MyInt"})
        assert mapper.pg_to_python("integer") == "MyInt"


class TestPythonImports:
    def setup_method(self):
        self.mapper = TypeMapper()

    def test_imports_for_decimal(self):
        imports = self.mapper.python_imports(["numeric"])
        assert "from decimal import Decimal" in imports

    def test_imports_for_datetime(self):
        imports = self.mapper.python_imports(["timestamp without time zone"])
        assert "from datetime import datetime" in imports

    def test_imports_for_date(self):
        imports = self.mapper.python_imports(["date"])
        assert "from datetime import date" in imports

    def test_imports_for_uuid(self):
        imports = self.mapper.python_imports(["uuid"])
        assert "from uuid import UUID" in imports

    def test_imports_for_jsonb(self):
        imports = self.mapper.python_imports(["jsonb"])
        assert "from typing import Any" in imports

    def test_imports_for_unknown_type(self):
        imports = self.mapper.python_imports(["custom_type"])
        assert "from typing import Any" in imports

    def test_imports_for_simple_types_empty(self):
        imports = self.mapper.python_imports(["integer", "text", "boolean"])
        assert len(imports) == 0

    def test_imports_for_array_uuid(self):
        imports = self.mapper.python_imports(["uuid[]"])
        assert "from uuid import UUID" in imports

    def test_imports_for_array_unknown(self):
        imports = self.mapper.python_imports(["mytype[]"])
        assert "from typing import Any" in imports

    def test_imports_for_multiple_types(self):
        imports = self.mapper.python_imports(["bigint", "uuid", "jsonb", "numeric"])
        assert "from uuid import UUID" in imports
        assert "from typing import Any" in imports
        assert "from decimal import Decimal" in imports

    def test_deduplication(self):
        # Two types that need the same import
        imports = self.mapper.python_imports(["json", "jsonb"])
        count = sum(1 for i in imports if i == "from typing import Any")
        assert count == 1

    def test_empty_list(self):
        imports = self.mapper.python_imports([])
        assert imports == set()
