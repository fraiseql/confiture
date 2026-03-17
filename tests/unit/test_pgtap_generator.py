"""Unit tests for PgTAPGenerator."""

from __future__ import annotations

from datetime import UTC
from unittest.mock import MagicMock, patch

from confiture.models.function_info import (
    FunctionCatalog,
    FunctionInfo,
    FunctionParam,
    Volatility,
)


def _make_catalog() -> FunctionCatalog:
    from datetime import datetime

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
        introspected_at=datetime.now(UTC).isoformat(),
        functions=[func],
    )


def test_pgtap_generator_produces_file():
    from confiture.core.pgtap_generator import PgTAPGenerator

    mock_conn = MagicMock()
    gen = PgTAPGenerator(mock_conn, schema="public")

    catalog = _make_catalog()
    with patch.object(gen._introspector, "introspect", return_value=catalog):
        pgtap_file = gen.generate()

    assert pgtap_file.database == "testdb"
    assert pgtap_file.function_count == 1
    assert len(pgtap_file.tests) > 0


def test_pgtap_generator_includes_existence_test():
    from confiture.core.pgtap_generator import PgTAPGenerator

    mock_conn = MagicMock()
    gen = PgTAPGenerator(mock_conn, schema="public")

    catalog = _make_catalog()
    with patch.object(gen._introspector, "introspect", return_value=catalog):
        pgtap_file = gen.generate()

    test_names = [t.test_name for t in pgtap_file.tests]
    assert any("exists" in name for name in test_names)


def test_pgtap_generator_render_valid_sql():
    from confiture.core.pgtap_generator import PgTAPGenerator

    mock_conn = MagicMock()
    gen = PgTAPGenerator(mock_conn, schema="public")

    catalog = _make_catalog()
    with patch.object(gen._introspector, "introspect", return_value=catalog):
        pgtap_file = gen.generate()

    sql = pgtap_file.render()
    assert "BEGIN;" in sql
    assert "ROLLBACK;" in sql
    assert "add" in sql


def test_pgtap_generator_skip_volatility():
    from confiture.core.pgtap_generator import PgTAPGenerator

    mock_conn = MagicMock()
    gen = PgTAPGenerator(mock_conn, schema="public", include_volatility=False)

    catalog = _make_catalog()
    with patch.object(gen._introspector, "introspect", return_value=catalog):
        pgtap_file = gen.generate()

    test_names = [t.test_name for t in pgtap_file.tests]
    assert not any(
        "volatility" in name.lower() or "immutable" in name.lower() for name in test_names
    )


def test_pgtap_generator_filters_by_name_pattern():
    from confiture.core.pgtap_generator import PgTAPGenerator

    mock_conn = MagicMock()
    gen = PgTAPGenerator(mock_conn, schema="public", name_pattern="fn_%")

    catalog = _make_catalog()
    with patch.object(gen._introspector, "introspect", return_value=catalog) as mock_intro:
        gen.generate()

    mock_intro.assert_called_once_with("public", name_pattern="fn_%")
