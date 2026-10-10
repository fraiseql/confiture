"""A routine PostgreSQL creates with another object is that object's, not a routine.

``CREATE TYPE span AS RANGE`` makes PostgreSQL create the type's constructor
functions (``span(int4, int4)``, ``span(int4, int4, text)``) and those of its
multirange (``span_multirange(…)``), each recorded in ``pg_depend`` as an
implicit dependent (``deptype = 'i'``) of the type. No tree declares them, so a
reader that listed them as routines made a database built from its own tree
differ from it: ``migrate diff`` proposed dropping them, and drift reported them
as extra routines.
"""

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture import platform
from confiture.core import live_catalog
from confiture.core.drift import SchemaDriftDetector

pytestmark = pytest.mark.integration

#: A range type beside a function of the tree's own, so drift compares routines
#: in the schema the range type is in.
TREE = """
CREATE TYPE span AS RANGE (subtype = int4);
CREATE FUNCTION fn() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;
"""


def _built(make_database: Callable[[str], str]) -> str:
    url = make_database("confiture_implicit")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(TREE)
    return url


def test_a_range_types_constructors_are_not_read_as_routines(
    fresh_database_factory: Callable[[str], str],
) -> None:
    with psycopg.connect(_built(fresh_database_factory)) as conn:
        model = live_catalog.read(conn, schemas=["public"], routines=True, other_objects=True)
        rows = live_catalog.routines(conn, ["public"], kinds=("f", "p", "a", "w"))
    assert sorted(ref.name for ref in model.routines) == ["fn"]
    assert [row.name for row in rows] == ["fn"]


def test_a_database_holding_a_declared_range_type_is_no_change_from_the_tree(
    fresh_database_factory: Callable[[str], str],
) -> None:
    diff = platform.diff(_built(fresh_database_factory), TREE)
    assert diff.changes == []


def test_a_range_types_constructors_are_not_extra_routines_to_drift(
    fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    tree = tmp_path / "schema.sql"
    tree.write_text(TREE)
    with psycopg.connect(_built(fresh_database_factory)) as conn:
        report = SchemaDriftDetector(conn).compare_with_schema_file(str(tree))
    assert [item.object_name for item in report.drift_items] == []
