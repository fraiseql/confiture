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

from confiture.core.linting.inventory import build_model
from confiture.core.live_catalog import read
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import SchemaModel, normalise_for_parity

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
    parsed = build_model(sql)
    with psycopg.connect(make_database("confiture_parity"), autocommit=True) as conn:
        conn.execute(sql)
        live = read(conn, schemas=_schemas(parsed), routines=True, views=True, triggers=True)
    return (
        normalise_for_parity(parsed).to_dict(),
        normalise_for_parity(live).to_dict(),
    )


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
