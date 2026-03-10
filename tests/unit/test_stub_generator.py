"""Unit tests for StubGenerator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from confiture.core.introspection.type_mapping import TypeMapper
from confiture.models.function_info import (
    FunctionCatalog,
    FunctionInfo,
    FunctionParam,
    Volatility,
)


def _make_catalog() -> FunctionCatalog:
    from datetime import datetime, timezone

    func = FunctionInfo(
        schema="public",
        name="add",
        oid=1,
        params=[
            FunctionParam(name="x", pg_type="integer"),
            FunctionParam(name="y", pg_type="integer"),
        ],
        return_type="integer",
        returns_set=False,
        volatility=Volatility.IMMUTABLE,
        is_procedure=False,
        language="sql",
        source="SELECT $1 + $2",
        estimated_cost=1.0,
    )
    return FunctionCatalog(
        database="testdb",
        schema="public",
        introspected_at=datetime.now(timezone.utc).isoformat(),
        functions=[func],
    )


def test_stub_generator_produce_stub_file():
    from confiture.core.stub_generator import StubGenerator

    mock_conn = MagicMock()
    gen = StubGenerator(mock_conn, schema="public")

    catalog = _make_catalog()
    with patch.object(gen._introspector, "introspect", return_value=catalog):
        stub_file = gen.generate()

    assert stub_file.database == "testdb"
    assert len(stub_file.functions) == 1
    assert stub_file.functions[0].name == "add"


def test_stub_generator_render_valid_python():
    from confiture.core.stub_generator import StubGenerator

    mock_conn = MagicMock()
    gen = StubGenerator(mock_conn, schema="public")

    catalog = _make_catalog()
    with patch.object(gen._introspector, "introspect", return_value=catalog):
        stub_file = gen.generate()

    code = stub_file.render()
    compile(code, "<stub>", "exec")  # must be valid Python
    assert "def add(" in code


def test_stub_generator_filters_by_name_pattern():
    from confiture.core.stub_generator import StubGenerator

    mock_conn = MagicMock()
    gen = StubGenerator(mock_conn, schema="public", name_pattern="fn_%")

    catalog = _make_catalog()
    with patch.object(gen._introspector, "introspect", return_value=catalog) as mock_intro:
        gen.generate()

    mock_intro.assert_called_once_with("public", include_triggers=False, name_pattern="fn_%")
