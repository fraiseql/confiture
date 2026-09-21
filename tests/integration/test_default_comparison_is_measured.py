"""A default the DDL wrote and the one PostgreSQL stored are one default — measured.

``default_mismatch`` was published and never emitted (#309) because PostgreSQL
stores a default analysed and text cannot compare the two sides: ``'x'`` comes back
``'x'::text``, ``TRUE`` comes back ``true``, ``1 + 2`` comes back ``(1 + 2)``.
``ddl_walk.canonical_default`` reads both as parse trees instead. This builds 23
defaults into a real database and holds the reader to all 23 — and holds the two
controls that must still differ, because a comparison that calls everything equal
passes the first test just as well.

Measured on PostgreSQL 18.4, 2026-09-21: compared as text, 10 of the 23 agree.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture.core import live_catalog
from confiture.core.ddl_walk import canonical_default
from confiture.core.drift import DriftType, SchemaDriftDetector, parse_expected_schema
from confiture.core.schema_model import Column

#: ``(column type, default as the DDL writes it)``.
SHAPES = [
    ("text", "'x'"),
    ("text[]", "'{}'"),
    ("varchar(10)", "'ab'"),
    ("boolean", "TRUE"),
    ("boolean", "false"),
    ("integer", "1 + 2"),
    ("jsonb", "CAST('{}' AS jsonb)"),
    ("jsonb", "'{}'::jsonb"),
    ("integer", "0"),
    ("integer", "-7"),
    ("timestamptz", "now()"),
    ("timestamptz", "CURRENT_TIMESTAMP"),
    ("uuid", "gen_random_uuid()"),
    ("text", "NULL"),
    ("numeric(10,2)", "1.50"),
    ("date", "'2020-01-01'"),
    ("text", "'it''s'"),
    ("int[]", "ARRAY[1,2]"),
    ("text", "lower('ABC')"),
    ("bigint", "42"),
    ("varchar(20)", "'active'::character varying"),
    ("interval", "'1 day'"),
    ("real", "1.5"),
]


def _ddl(shapes: list[tuple[str, str]]) -> str:
    columns = ",\n".join(
        f"    c{n:02d} {type_} DEFAULT {default}" for n, (type_, default) in enumerate(shapes)
    )
    return f"CREATE TABLE shapes (\n{columns}\n);\n"


def _columns(ddl: str, url: str) -> tuple[dict[str, Column], dict[str, Column]]:
    """Each column as the DDL declares it and as the database built from it holds it."""
    (declared,) = parse_expected_schema(ddl).model.tables.values()
    with psycopg.connect(url) as conn:
        (stored,) = live_catalog.read(conn, schemas=["public"]).tables.values()
    return {c.folded: c for c in declared.columns}, {c.folded: c for c in stored.columns}


@pytest.fixture
def build(fresh_database_factory: Callable[[str], str]) -> Callable[[str], str]:
    """``build(ddl) -> url``: *ddl* applied to a database of its own."""

    def make(ddl: str) -> str:
        url = fresh_database_factory("confiture_defaults")
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(ddl)
        return url

    return make


def test_the_shapes_are_the_ones_measured() -> None:
    """A floor: the claim in the docstring is about 23 shapes."""
    assert len(SHAPES) == 23


def test_every_default_compares_equal_to_what_postgres_stored(
    build: Callable[[str], str],
) -> None:
    ddl = _ddl(SHAPES)
    declared, stored = _columns(ddl, build(ddl))

    def canonical(column: Column, type_text: str | None) -> str | None:
        return canonical_default(column.default, type_text)

    unequal = [
        (name, declared[name].default, stored[name].default)
        for name in declared
        if canonical(declared[name], stored[name].type_text)
        != canonical(stored[name], stored[name].type_text)
    ]
    assert unequal == []


def test_as_text_they_do_not_agree(build: Callable[[str], str]) -> None:
    """The control that makes the result mean something: PostgreSQL rewrote defaults."""
    url = build(_ddl(SHAPES))
    with psycopg.connect(url) as conn:
        stored = dict(
            conn.execute(
                "SELECT a.attname, pg_get_expr(d.adbin, d.adrelid) FROM pg_attribute a"
                " LEFT JOIN pg_attrdef d ON (d.adrelid, d.adnum) = (a.attrelid, a.attnum)"
                " WHERE a.attrelid = 'shapes'::regclass AND a.attnum > 0"
            ).fetchall()
        )
    as_text = sum(1 for n, (_type, written) in enumerate(SHAPES) if stored[f"c{n:02d}"] == written)
    assert as_text < len(SHAPES), "PostgreSQL stored every default as written"


def test_drift_reports_no_default_mismatch_on_the_database_the_ddl_built(
    build: Callable[[str], str], tmp_path: Path
) -> None:
    ddl = _ddl(SHAPES)
    url = build(ddl)
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(ddl)

    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn).compare_with_schema_file(str(schema_file))

    assert report.drift_items == [], report.to_dict()


def test_two_different_defaults_stay_different(build: Callable[[str], str], tmp_path: Path) -> None:
    """The DDL says ``'x'`` and ``0``; the database holds ``'y'`` and ``1``."""
    written = [("text", "'x'"), ("integer", "0")]
    url = build(_ddl([("text", "'y'"), ("integer", "1")]))
    ddl = _ddl(written)
    declared, stored = _columns(ddl, url)

    for name in ("c00", "c01"):
        type_text = stored[name].type_text
        assert canonical_default(declared[name].default, type_text) != canonical_default(
            stored[name].default, type_text
        )

    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(ddl)
    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn).compare_with_schema_file(str(schema_file))

    assert [(i.drift_type, i.object_name) for i in report.drift_items] == [
        (DriftType.DEFAULT_MISMATCH, "public.shapes.c00"),
        (DriftType.DEFAULT_MISMATCH, "public.shapes.c01"),
    ]
