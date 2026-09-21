"""The live side of a drift comparison reads the type PostgreSQL actually stores.

``SchemaAnalyzer._read_columns`` read ``information_schema.columns.data_type``,
which spells an array ``ARRAY``, a user type ``USER-DEFINED``, and drops every
typmod. So ``tags TEXT[]`` in the DDL met ``array`` from the database, and eight
columns of the #302 corpus reported a ``type_mismatch`` on a database applied
verbatim from that DDL.

``format_type(atttypid, atttypmod)`` is PostgreSQL's own answer to "what type is
this column", and it is the same vocabulary the DDL is written in.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from confiture.core.drift import SchemaDriftDetector
from confiture.core.psql_applier import apply_sql_via_psql
from confiture.core.schema_model import Column, Table

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "live_drift_corpus"


@pytest.fixture
def types_database(fresh_database: str) -> str:
    """The corpus' schema, extension, domain, enum and type-zoo table."""
    for name in ("010_schema.sql", "020_tables.sql", "030_types.sql"):
        apply_sql_via_psql(fresh_database, sql=(CORPUS / name).read_text(encoding="utf-8"))
    return fresh_database


def live_core(conn: psycopg.Connection) -> dict[str, Table]:
    """The live ``core`` schema as drift reads it, keyed ``schema.table``."""
    model = SchemaDriftDetector(conn).get_live_schema(["core"])
    return {f"{t.schema}.{t.name}": t for t in model.tables.values()}


def columns_of(url: str, table: str) -> dict[str, Column]:
    with psycopg.connect(url) as conn:
        return {c.folded: c for c in live_core(conn)[table].columns}


#: ``(column, the type PostgreSQL stores)`` — every row measured on 18.4.
EXPECTED_TYPES = [
    ("id", "bigint"),
    ("counter", "integer"),
    ("label", "character varying(50)"),
    ("tags", "text[]"),
    ("scores", "integer[]"),
    ("grid", "integer[]"),
    ("doc", "json"),
    ("flags", "bit(3)"),
    ("vflags", "bit varying(8)"),
    ("email", "citext"),
    ("amount", "numeric(10,2)"),
    ("amounts", "numeric(10,2)[]"),
    ("code", "character(4)"),
    ("seen_at", "timestamp with time zone"),
    ("rank", "core.pos"),
    ("feeling", "core.mood"),
    ("ts3", "timestamp(3) without time zone"),
    ("t3", "time(3) without time zone"),
    ("vb", "bit varying(8)"),
    ("c1", "character(1)"),
]


@pytest.mark.parametrize(("column", "written"), EXPECTED_TYPES)
def test_the_live_type_is_what_postgres_stores(
    types_database: str, column: str, written: str
) -> None:
    assert columns_of(types_database, "core.tb_types")[column].type_text == written


def test_nullability_and_defaults_survive_the_rewrite(types_database: str) -> None:
    columns = columns_of(types_database, "core.tb_types")
    assert columns["label"].not_null is True
    assert columns["tags"].not_null is False
    assert (columns["id"].default or "").startswith("nextval(")


def test_a_partitioned_parent_is_still_a_table(types_database: str) -> None:
    """``relkind IN ('r','p')``, not ``'r'``: `information_schema` called a
    partitioned parent a BASE TABLE and the expected side models it, so a live
    read filtered to ordinary tables would report it missing."""
    with psycopg.connect(types_database) as conn:
        tables = live_core(conn)
    assert "core.tb_event" in tables
    assert "core.tb_event_2026" in tables


def test_a_dropped_column_is_not_reported(types_database: str) -> None:
    """``NOT attisdropped`` is required: ``pg_attribute`` keeps the tombstone."""
    with psycopg.connect(types_database) as conn:
        conn.execute("ALTER TABLE core.tb_types DROP COLUMN counter")
        conn.commit()
        columns = [c.folded for c in live_core(conn)["core.tb_types"].columns]
    assert "counter" not in columns
    assert all(not name.startswith("........pg.dropped") for name in columns)


def test_declaration_order_is_preserved(types_database: str) -> None:
    """``_compare_column_order`` reads declaration order off the model's columns."""
    assert list(columns_of(types_database, "core.tb_widget")) == [
        "id",
        "serial",
        "maybe_null",
        "ratio",
    ]
