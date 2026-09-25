"""Every example's generated migration applies to an empty database, and undoes (#335).

The diff goldens are what ``migrate diff --generate`` writes for each schema tree
the repository ships, from an empty database to the tree
(``scripts/refresh_model_goldens.py``). Before #335 only three of them applied:
schemas, extensions and enum types came after the tables that used them, tables
came by name rather than by foreign key, and an added table's indexes were not
written at all. Each is applied here, its down file after it, and the up again —
statement by statement, as ``CREATE INDEX CONCURRENTLY`` requires.

The before/after pairs an example ships are applied the same way on top of the
migration that builds their *before*.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from confiture.core import sql_lexer

pytestmark = pytest.mark.integration

GOLDENS = Path(__file__).resolve().parents[1] / "fixtures" / "model_goldens" / "diff"
PAIRS = sorted(p.name.removesuffix(".old.up.sql") for p in GOLDENS.glob("*.old.up.sql"))
TREES = sorted(
    name for p in GOLDENS.glob("*.up.sql") if (name := p.name.removesuffix(".up.sql")) not in PAIRS
)

#: A pair whose down file PostgreSQL refuses, with the reason. Each entry is
#: asserted to still fail; the day it applies, the entry goes.
UNDONE: dict[str, str] = {}


def _apply(conn: psycopg.Connection, path: Path) -> None:
    for statement in sql_lexer.split_statements(path.read_text()):
        if sql_lexer.code_text(statement).text.strip():
            conn.execute(statement)


def _relations(conn: psycopg.Connection) -> set[tuple[str, str, str]]:
    rows = conn.execute(
        "SELECT n.nspname, c.relname, c.relkind FROM pg_class c"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')"
    ).fetchall()
    return set(rows)


@pytest.mark.parametrize("tree", TREES)
def test_the_tree_is_created_undone_and_created_again(fresh_database: str, tree: str) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        _apply(conn, GOLDENS / f"{tree}.up.sql")
        created = _relations(conn)
        _apply(conn, GOLDENS / f"{tree}.down.sql")
        _apply(conn, GOLDENS / f"{tree}.up.sql")
        assert _relations(conn) == created


@pytest.mark.parametrize("pair", PAIRS)
def test_the_pair_applies_on_its_before(fresh_database: str, pair: str) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        _apply(conn, GOLDENS / f"{pair}.old.up.sql")
        _apply(conn, GOLDENS / f"{pair}.up.sql")
        if pair in UNDONE:
            with pytest.raises(psycopg.Error):
                _apply(conn, GOLDENS / f"{pair}.down.sql")
            return
        _apply(conn, GOLDENS / f"{pair}.down.sql")
        _apply(conn, GOLDENS / f"{pair}.up.sql")


def test_every_undone_entry_is_a_pair() -> None:
    assert set(UNDONE) <= set(PAIRS)
