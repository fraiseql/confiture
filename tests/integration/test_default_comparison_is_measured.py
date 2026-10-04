"""A default the DDL wrote and the one PostgreSQL stored are one default — measured.

``default_mismatch`` was published and never emitted (#309) because PostgreSQL
stores a default analysed and text cannot compare the two sides: ``'x'`` comes back
``'x'::text``, ``TRUE`` comes back ``true``, ``1 + 2`` comes back ``(1 + 2)``.
``ddl_walk.same_value`` reads both as parse trees instead. This builds 24
defaults into a real database and holds the reader to all 24 — and holds the two
controls that must still differ, because a comparison that calls everything equal
passes the first test just as well.

Measured on PostgreSQL 18.4, 2026-09-21: compared as text, 10 of the 24 agree.

A constant is opaque to a parse tree, and PostgreSQL stores one in its type's output
spelling: a ``jsonb`` object with its keys sorted (#564), ``'2024-1-1'`` as
``'2024-01-01'``, ``'t'`` as ``true``. :data:`RESPELLED` holds those, each beside a
:data:`CONTROLS` row that writes another value of the same type, and both are held
through ``confiture drift`` and ``migrate diff --from db``: the server spells the
tree's constants (``server_constants``), so the two sides compare as values.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture.core import live_catalog
from confiture.core.ddl_walk import same_value
from confiture.core.drift import DriftType, SchemaDriftDetector, parse_expected_schema
from confiture.core.schema_model import Column
from confiture.core.schema_sources import diff

#: ``(column type, default as the DDL writes it)``.
SHAPES = [
    ("text", "'x'"),
    ("text", "'active'"),
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


#: Constants PostgreSQL stores in another spelling than the one written, ``(column
#: type, as written)``. Measured on PostgreSQL 18.1, 2026-10-04: all but
#: :data:`STORED_AS_WRITTEN` come back re-spelled.
RESPELLED = [
    (
        "jsonb",
        """'{"max_attempts": 3, "backoff": "exponential", "initial_delay_ms": 1000}'::jsonb""",
    ),
    ("jsonb", """'{"a": 1, "bb": 2}'::jsonb"""),
    ("jsonb", """'{"a":1,"a":2}'"""),
    ("date", "'2024-1-1'"),
    ("date", "'2024-1-1'::date"),
    ("boolean", "'t'"),
    ("boolean", "'t'::boolean"),
    ("interval", "'1 day 2 hours'"),
    ("interval", "interval '90 minutes'"),
    ("uuid", "'A0EEBC99-9C0B-4EF8-BB6D-6BB9BD380A11'"),
    ("inet", "'10.0.0.1/32'"),
    ("integer[]", "'{1, 2}'"),
    ("timestamptz", "'2024-01-01 00:00'"),
    ("timestamp", "'2024-01-01T00:00:00'"),
    ("double precision", "'1e3'"),
    ("bytea", "'\\x00FF'"),
    ("time", "'1:2'"),
    ("numeric(10,2)", "'1.5'"),
    ("integer", "'7'"),
    ("text", "123"),
]

#: The two of :data:`RESPELLED` stored as written: #564's object whose keys are
#: already in jsonb's order, and a number in a ``text`` column, which must not
#: compare equal to the number in an ``integer`` one.
STORED_AS_WRITTEN = ["""'{"a": 1, "bb": 2}'::jsonb""", "123"]

#: Each of :data:`RESPELLED`, holding another value of its type.
CONTROLS = [
    ("jsonb", """'{"max_attempts": 4, "backoff": "exponential", "initial_delay_ms": 1000}'"""),
    ("jsonb", """'{"a": 1, "bb": 3}'"""),
    ("jsonb", """'{"a": 1}'"""),
    ("date", "'2024-01-02'"),
    ("date", "'2024-01-02'"),
    ("boolean", "false"),
    ("boolean", "false"),
    ("interval", "'1 day 03:00:00'"),
    ("interval", "'01:31:00'"),
    ("uuid", "'b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'"),
    ("inet", "'10.0.0.2'"),
    ("integer[]", "'{1,3}'"),
    ("timestamptz", "'2024-01-01 00:01'"),
    ("timestamp", "'2024-01-01 00:01:00'"),
    ("double precision", "1001"),
    ("bytea", "'\\x00fe'"),
    ("time", "'01:03:00'"),
    ("numeric(10,2)", "1.6"),
    ("integer", "8"),
    ("text", "'124'"),
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
    """A floor: the claim in the docstring is about 24 shapes."""
    assert len(SHAPES) == 24


def test_every_default_compares_equal_to_what_postgres_stored(
    build: Callable[[str], str],
) -> None:
    ddl = _ddl(SHAPES)
    declared, stored = _columns(ddl, build(ddl))

    unequal = [
        (name, declared[name].default, stored[name].default)
        for name in declared
        if not same_value(
            declared[name].default,
            stored[name].default,
            slot="default",
            types=(stored[name].type_text, stored[name].type_text),
        )
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
        assert not same_value(
            declared[name].default,
            stored[name].default,
            slot="default",
            types=(type_text, type_text),
        )

    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(ddl)
    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn).compare_with_schema_file(str(schema_file))

    assert [(i.drift_type, i.object_name) for i in report.drift_items] == [
        (DriftType.DEFAULT_MISMATCH, "public.shapes.c00"),
        (DriftType.DEFAULT_MISMATCH, "public.shapes.c01"),
    ]


def _drift(ddl: str, url: str, tmp_path: Path) -> list[tuple[DriftType, str]]:
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(ddl)
    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn).compare_with_schema_file(str(schema_file))
    return [(item.drift_type, item.object_name) for item in report.drift_items]


def _diff(ddl: str, url: str, tmp_path: Path) -> list[str]:
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(ddl)
    return [str(change) for change in diff(url, schema_file).changes]


def test_the_respelled_shapes_each_have_a_control() -> None:
    assert [type_ for type_, _ in RESPELLED] == [type_ for type_, _ in CONTROLS]


def test_postgres_respelled_every_constant(build: Callable[[str], str]) -> None:
    """The control on the table itself: PostgreSQL re-spelled them."""
    url = build(_ddl(RESPELLED))
    with psycopg.connect(url) as conn:
        stored = dict(
            conn.execute(
                "SELECT a.attname, pg_get_expr(d.adbin, d.adrelid) FROM pg_attribute a"
                " JOIN pg_attrdef d ON (d.adrelid, d.adnum) = (a.attrelid, a.attnum)"
                " WHERE a.attrelid = 'shapes'::regclass"
            ).fetchall()
        )
    assert [
        written for n, (_type, written) in enumerate(RESPELLED) if stored[f"c{n:02d}"] == written
    ] == STORED_AS_WRITTEN


def test_drift_reads_a_respelled_constant_as_the_same_value(
    build: Callable[[str], str], tmp_path: Path
) -> None:
    ddl = _ddl(RESPELLED)
    assert _drift(ddl, build(ddl), tmp_path) == []


def test_diff_from_the_database_reads_a_respelled_constant_as_the_same_value(
    build: Callable[[str], str], tmp_path: Path
) -> None:
    ddl = _ddl(RESPELLED)
    assert _diff(ddl, build(ddl), tmp_path) == []


def test_drift_reports_every_control(build: Callable[[str], str], tmp_path: Path) -> None:
    url = build(_ddl(CONTROLS))
    assert _drift(_ddl(RESPELLED), url, tmp_path) == [
        (DriftType.DEFAULT_MISMATCH, f"public.shapes.c{n:02d}") for n in range(len(CONTROLS))
    ]


def test_diff_from_the_database_reports_every_control(
    build: Callable[[str], str], tmp_path: Path
) -> None:
    url = build(_ddl(CONTROLS))
    assert len(_diff(_ddl(RESPELLED), url, tmp_path)) == len(CONTROLS)
