"""The drift expected-schema parser reads qualified DDL through pglast (#227).

The regex parser matched ``CREATE TABLE tenant.tb_user`` with ``(\\w+)`` and
recorded a table called ``tenant``; ``CREATE SCHEMA`` produced nothing and
every schema-qualified table went unchecked while its schema name showed up
as a critical ``missing_table``. Both sides of a comparison are keyed
``schema.table`` now, an unqualified name resolves to the default schema, and
the parser reports which schemas the DDL declares so the live side can read
exactly those.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from confiture.core.drift import DriftType, SchemaDriftDetector, parse_expected_schema
from confiture.core.schema_model import Constraint, SchemaModel, Table
from confiture.exceptions import SchemaError
from tests.unit._schema_models import model_of

TENANT = (
    "CREATE SCHEMA tenant;\n"
    "CREATE TABLE tenant.tb_user (id bigint PRIMARY KEY, name text NOT NULL DEFAULT 'x');\n"
)

#: The primary key PostgreSQL records for ``TENANT``'s unnamed one.
PKEY = Constraint(kind="primary_key", name="tb_user_pkey", columns=("id",))


def _detector(ignore: list[str] | None = None) -> SchemaDriftDetector:
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("db",)
    return SchemaDriftDetector(conn, ignore_tables=ignore)


def _tables(model: SchemaModel) -> dict[str, Table]:
    """The model's tables keyed ``schema.table``, as a finding names them."""
    return {f"{t.schema}.{t.name}": t for t in model.tables.values()}


def _facts(table: Table) -> dict[str, dict[str, object]]:
    """Each column as ``{type, nullable, default}`` — what a finding reports."""
    return {
        c.name: {"type": c.type_text, "nullable": not c.not_null, "default": c.default}
        for c in table.columns
    }


def test_create_schema_alone_yields_no_table_but_declares_the_schema() -> None:
    expected = parse_expected_schema("CREATE SCHEMA tenant;")
    assert expected.model.tables == {}
    assert expected.schemas == frozenset({"public", "tenant"})


def test_a_qualified_table_is_keyed_schema_dot_table_with_its_columns() -> None:
    expected = parse_expected_schema(TENANT)
    tables = _tables(expected.model)
    assert list(tables) == ["tenant.tb_user"]
    assert _facts(tables["tenant.tb_user"]) == {
        "id": {"type": "bigint", "nullable": False, "default": None},
        "name": {"type": "text", "nullable": False, "default": "'x'"},
    }
    assert expected.schemas == frozenset({"public", "tenant"})


def test_an_unqualified_table_lands_in_the_default_schema() -> None:
    assert list(_tables(parse_expected_schema("CREATE TABLE plain (id int);").model)) == [
        "public.plain"
    ]
    assert list(
        _tables(parse_expected_schema("CREATE TABLE plain (id int);", default_schema="app").model)
    ) == ["app.plain"]
    assert parse_expected_schema(
        "CREATE TABLE plain (id int);", default_schema="app"
    ).schemas == frozenset({"app"})


def test_quoted_mixed_case_identifiers_keep_their_case() -> None:
    expected = parse_expected_schema('CREATE TABLE "Tenant"."Tb" ("Id" int NOT NULL);')
    tables = _tables(expected.model)
    assert list(tables) == ["Tenant.Tb"]
    assert _facts(tables["Tenant.Tb"]) == {
        "Id": {"type": "integer", "nullable": False, "default": None}
    }
    assert "Tenant" in expected.schemas


def test_a_create_table_inside_a_function_body_is_not_a_table() -> None:
    sql = (
        "CREATE FUNCTION mk() RETURNS void LANGUAGE plpgsql AS $$\n"
        "BEGIN\n  CREATE TABLE scratch (id int);\nEND\n$$;\n"
        "CREATE TABLE real_one (id int);\n"
    )
    assert list(_tables(parse_expected_schema(sql).model)) == ["public.real_one"]


def test_indexes_are_keyed_by_the_qualified_table() -> None:
    sql = TENANT + "CREATE INDEX idx_user_name ON tenant.tb_user (name);\n"
    tables = _tables(parse_expected_schema(sql).model)
    assert {name: [ix.name for ix in t.indexes] for name, t in tables.items()} == {
        "tenant.tb_user": ["idx_user_name"]
    }
    assert [ix.table for ix in tables["tenant.tb_user"].indexes] == ["tenant.tb_user"]


def test_a_partition_child_inherits_its_parents_columns() -> None:
    sql = (
        "CREATE TABLE app.events (id bigint NOT NULL, at date NOT NULL) PARTITION BY RANGE (at);\n"
        "CREATE TABLE app.events_2026 PARTITION OF app.events FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');\n"
    )
    tables = _tables(parse_expected_schema(sql).model)
    assert [c.name for c in tables["app.events_2026"].columns] == ["id", "at"]


def test_unparseable_ddl_is_a_schema_error_not_an_empty_expectation() -> None:
    with pytest.raises(SchemaError) as excinfo:
        parse_expected_schema("CREATE TABEL broken (;")
    assert excinfo.value.error_code == "SCHEMA_202"


def test_the_expected_side_is_the_schema_model() -> None:
    # The detector's own `_parse_schema_from_sql` and its dict shape are gone:
    # the expected side is the lint inventory's schema model, as the live side is.
    expected = parse_expected_schema(TENANT)
    assert isinstance(expected.model, SchemaModel)
    assert list(_tables(expected.model)) == ["tenant.tb_user"]


def test_qualified_expected_against_qualified_live_reports_no_missing_table() -> None:
    expected = parse_expected_schema(TENANT + "CREATE TABLE plain (id int);").model
    live = model_of(
        {
            "tenant.tb_user": {
                "id": {"type": "bigint", "nullable": False},
                "name": {"type": "text", "nullable": False, "default": "'x'::text"},
            },
            "public.plain": {"id": "integer"},
        },
        constraints={"tenant.tb_user": [PKEY]},
    )
    report = _detector().compare_schemas(expected, live)
    assert [i for i in report.drift_items if i.drift_type == DriftType.MISSING_TABLE] == []
    assert report.tables_checked == 2


def test_a_missing_column_names_the_qualified_table() -> None:
    expected = parse_expected_schema(TENANT).model
    live = model_of(
        {"tenant.tb_user": {"id": {"type": "bigint", "nullable": False}}},
        constraints={"tenant.tb_user": [PKEY]},
    )
    report = _detector().compare_schemas(expected, live)
    assert [(i.drift_type, i.object_name) for i in report.drift_items] == [
        (DriftType.MISSING_COLUMN, "tenant.tb_user.name")
    ]


def test_ignore_tables_accepts_bare_and_qualified_names() -> None:
    expected = model_of({"tenant.tb_x": {}, "public.tb_x": {}, "tenant.tb_y": {}})
    live = SchemaModel()
    report = _detector(ignore=["tb_x", "tenant.tb_y"]).compare_schemas(expected, live)
    assert report.drift_items == []
    report = _detector(ignore=["tenant.tb_x"]).compare_schemas(expected, live)
    assert sorted(i.object_name for i in report.drift_items) == ["public.tb_x", "tenant.tb_y"]


def test_confitures_own_ledger_is_ignored_in_any_schema() -> None:
    live = model_of({"public.tb_confiture": {}, "tenant.tb_confiture": {}})
    report = _detector().compare_schemas(SchemaModel(), live)
    assert report.drift_items == []


def test_confitures_checkpoint_table_is_not_drift() -> None:
    # The online runner keeps its checkpoints beside the ledger; neither is schema drift.
    live = model_of({"public.tb_confiture_steps": {}})
    assert _detector().compare_schemas(SchemaModel(), live).drift_items == []


def test_confitures_lock_table_is_not_drift() -> None:
    # ``migrate up`` creates the lock-holder table; a deployer who then runs
    # ``drift`` against the schema they just applied must see nothing.
    live = model_of({"public.confiture_lock_holder": {}})
    report = _detector().compare_schemas(SchemaModel(), live)
    assert report.drift_items == []
