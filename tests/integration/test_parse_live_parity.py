"""A database built from a tree, read live, is the tree.

``core/live_catalog.read`` reads ``pg_catalog`` into the schema model; the lint
inventory reads the DDL into the same model. Applied verbatim, the two must be
**equal** once ``schema_model.normalise_for_parity`` has applied the
disagreements PostgreSQL itself introduces — each of which is measured in
``test_parity_normalisations_are_measured.py`` and cannot outlive its cause.

Whatever else differs is a bug in one of the two readers, fixed at that reader.
Before this module there was no way to ask the question: the live side was read
into a dict keyed by strings and the parse side into three unrelated models, so
``confiture drift`` compared two representations and reported their differences
as drift.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from test_diff_goldens import goldens

from confiture.core.live_catalog import read
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import SECTIONS, SchemaModel, normalise_for_parity
from confiture.core.schema_read import read_text

TREES = {tree.name: tree for tree in goldens.TREES}


def _schemas(model: SchemaModel) -> list[str]:
    declared = {
        ref.schema
        for ref in (
            *model.tables,
            *model.enum_types,
            *model.sequences,
            *model.routines,
            *model.views,
            *model.triggers,
        )
    }
    return sorted(declared | {DEFAULT_SCHEMA})


def _parity(
    tree_name: str, make_database: Callable[[str], str], tmp_path: Path
) -> tuple[dict, dict]:
    sql = goldens.build(TREES[tree_name], tmp_path / f"{tree_name}.sql").read_text()
    return _parity_of(sql, make_database)


def _parity_of(sql: str, make_database: Callable[[str], str]) -> tuple[dict, dict]:
    parsed = read_text(sql).model
    with psycopg.connect(make_database("confiture_parity"), autocommit=True) as conn:
        conn.execute(sql)
        live = read(conn, schemas=_schemas(parsed), routines=True, views=True, triggers=True)
    # Compared in the sections both readers read: coverage is what each read,
    # not what the schema is.
    shared = {s for s in SECTIONS if parsed.coverage.shared(live.coverage, s)}

    def within(model: SchemaModel) -> dict:
        return {k: v for k, v in normalise_for_parity(model).to_dict().items() if k in shared}

    return within(parsed), within(live)


def _explain(parsed: dict, live: dict) -> str:
    return "parse:\n" + json.dumps(parsed, indent=1) + "\nlive:\n" + json.dumps(live, indent=1)


@pytest.mark.parametrize(
    "tree_name",
    [
        "db-schema",
        "01-basic-migration",
        "02-fraiseql-integration",
        "04-production-sync-anonymization",
        "05-multi-environment-workflow",
        "06-prep-seed-validation",
        "07-comment-validation",
        "basic",
    ],
)
def test_a_database_built_from_a_tree_reads_back_as_the_tree(
    tree_name: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    parsed, live = _parity(tree_name, fresh_database_factory, tmp_path)
    assert live == parsed, _explain(parsed, live)


def test_every_routine_and_view_shape_reads_back_as_itself(
    fresh_database_factory: Callable[[str], str],
) -> None:
    """The routine goldens' tree: a trigger function, a procedure, VARIADIC and OUT
    arguments, arrays, a schema-qualified type, types PostgreSQL spells its own way,
    a view in a second schema and a materialized view."""
    sql = (goldens.ROUTINE_FIXTURES / "schema.sql").read_text()
    sql += "\nCREATE UNIQUE INDEX mv_things_id ON public.mv_things (id);\n"
    parsed, live = _parity_of(sql, fresh_database_factory)
    assert len(parsed["routines"]) == 10 and len(parsed["views"]) == 3, parsed
    assert len(parsed["triggers"]) == 1, parsed
    assert live == parsed, _explain(parsed, live)


EXCLUSIONS = """
CREATE TABLE booking (
    room_id INT,
    during TSRANGE,
    note TEXT,
    CONSTRAINT no_overlap EXCLUDE USING gist (during WITH &&) WHERE (room_id > 0),
    EXCLUDE USING gist (during WITH &&) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT by_lower EXCLUDE USING btree ((lower(note)) WITH =)
);
"""


def test_an_exclusion_constraint_reads_back_as_itself(
    fresh_database_factory: Callable[[str], str],
) -> None:
    """#322: named and unnamed, with an expression, a predicate and deferral."""
    parsed, live = _parity_of(EXCLUSIONS, fresh_database_factory)
    (table,) = parsed["tables"]
    assert [c["kind"] for c in table["constraints"]] == ["exclusion"] * 3, parsed
    assert live == parsed, _explain(parsed, live)


def test_the_issues_exclusion_constraint_reads_back_as_itself(
    fresh_database_factory: Callable[[str], str],
) -> None:
    """``room_id WITH =`` beside a range needs ``btree_gist``'s operator class."""
    url = fresh_database_factory("confiture_parity")
    with psycopg.connect(url, autocommit=True) as conn:
        available = conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'btree_gist'"
        ).fetchone()
    if available is None:
        pytest.skip("btree_gist is not available on this server; the range-only case runs")
    sql = (
        "CREATE EXTENSION IF NOT EXISTS btree_gist;\n"
        "CREATE TABLE tb_booking (room_id INT, during TSRANGE,"
        " CONSTRAINT no_overlap EXCLUDE USING gist (room_id WITH =, during WITH &&));\n"
    )
    parsed, live = _parity_of(sql, fresh_database_factory)
    assert live == parsed, _explain(parsed, live)


def test_a_dropped_constraint_reads_back_as_absent(
    fresh_database_factory: Callable[[str], str],
) -> None:
    """#624: the keys a later ``DROP CONSTRAINT`` drops, a primary key's among them."""
    sql = (
        "CREATE TABLE tb_code (id INT, code TEXT, kind TEXT,"
        " CONSTRAINT tb_code_pkey PRIMARY KEY (id),"
        " CONSTRAINT tb_code_code_key UNIQUE (code),"
        " CONSTRAINT tb_code_kind_check CHECK (kind <> ''));\n"
        "ALTER TABLE tb_code DROP CONSTRAINT tb_code_code_key;\n"
        "ALTER TABLE tb_code DROP CONSTRAINT tb_code_pkey,"
        " ADD CONSTRAINT tb_code_pkey PRIMARY KEY (id, kind);\n"
    )
    parsed, live = _parity_of(sql, fresh_database_factory)
    (table,) = parsed["tables"]
    assert [c["kind"] for c in table["constraints"]] == ["check", "primary_key"], parsed
    assert live == parsed, _explain(parsed, live)


TEMPORAL_KEYS = """
CREATE TABLE p (
    id INT4RANGE,
    valid DATERANGE,
    CONSTRAINT p_pkey PRIMARY KEY (id, valid WITHOUT OVERLAPS)
);
CREATE TABLE u (
    id INT4RANGE,
    valid DATERANGE,
    UNIQUE (id, valid WITHOUT OVERLAPS),
    UNIQUE (id, valid)
);
CREATE TABLE q (id INT4RANGE, valid DATERANGE, UNIQUE (id, valid));
CREATE TABLE c (
    id INT4RANGE,
    valid DATERANGE,
    CONSTRAINT c_fk FOREIGN KEY (id, PERIOD valid) REFERENCES p (id, PERIOD valid),
    FOREIGN KEY (id, valid) REFERENCES q (id, valid)
);
"""


def test_a_temporal_key_reads_back_as_itself(
    fresh_database_factory: Callable[[str], str],
) -> None:
    """#604: ``WITHOUT OVERLAPS`` and ``PERIOD``, beside the plain key on the same columns.

    PostgreSQL 18 is the first server that can hold one; on an older server the
    statement is a syntax error and there is nothing to read back.
    """
    url = fresh_database_factory("confiture_parity")
    with psycopg.connect(url, autocommit=True) as conn:
        (version,) = conn.execute("SHOW server_version_num").fetchone() or ("0",)
    if int(version) < 180000:
        pytest.skip("temporal keys need PostgreSQL 18")
    parsed, live = _parity_of(TEMPORAL_KEYS, fresh_database_factory)
    temporal = [c["kind"] for t in parsed["tables"] for c in t["constraints"] if c["temporal"]]
    assert sorted(temporal) == ["foreign_key", "primary_key", "unique"], parsed
    assert live == parsed, _explain(parsed, live)
