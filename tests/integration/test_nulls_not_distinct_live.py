"""``NULLS NOT DISTINCT`` read from a live database, and drift on it (#623).

The catalog holds it in ``pg_index.indnullsnotdistinct``; ``pg_get_indexdef``
writes it after the key list (``… (a, b) NULLS NOT DISTINCT WHERE …``) and
``pg_get_constraintdef`` after the keyword (``UNIQUE NULLS NOT DISTINCT (a, b)``),
which is what the one live reader parses.
"""

from pathlib import Path

import psycopg
import pytest

from confiture import platform
from confiture.core import live_catalog
from confiture.core.drift import DriftType, SchemaDriftDetector
from confiture.core.schema_change import (
    IndexAdded,
    IndexDropped,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)

TABLE = "CREATE TABLE tb_node (id int PRIMARY KEY, fk_parent int, name text{key});\n"
OLD = (
    TABLE.format(key=", CONSTRAINT uq_node_name UNIQUE (name)")
    + "CREATE UNIQUE INDEX ux_node ON tb_node (fk_parent, name);\n"
)
NEW = (
    TABLE.format(key=", CONSTRAINT uq_node_name UNIQUE NULLS NOT DISTINCT (name)")
    + "CREATE UNIQUE INDEX ux_node ON tb_node (fk_parent, name) NULLS NOT DISTINCT;\n"
)


def _built(url: str, sql: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql)


def _drift(url: str, tree: Path) -> list[tuple[str, str]]:
    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn).compare_with_schema_file(str(tree))
    return sorted((item.drift_type.value, item.object_name) for item in report.drift_items)


def test_the_live_reader_holds_it(fresh_database: str) -> None:
    _built(fresh_database, NEW)
    with psycopg.connect(fresh_database) as conn:
        model = live_catalog.read(conn, schemas=["public"])
    (table,) = model.tables.values()
    (key,) = table.constraints_of("unique")
    assert key.nulls_not_distinct is True
    held = {index.name: index.nulls_not_distinct for index in table.indexes}
    assert held["ux_node"] is True
    assert held["uq_node_name"] is True  # the constraint's backing index
    assert held["tb_node_pkey"] is False


@pytest.mark.parametrize("sql", [OLD, NEW], ids=["without", "with"])
def test_a_database_built_from_a_tree_has_no_drift_against_it(
    fresh_database: str, tmp_path: Path, sql: str
) -> None:
    _built(fresh_database, sql)
    tree = tmp_path / "schema.sql"
    tree.write_text(sql)
    assert _drift(fresh_database, tree) == []


def test_a_database_built_from_the_old_tree_drifts_against_the_new(
    fresh_database: str, tmp_path: Path
) -> None:
    _built(fresh_database, OLD)
    tree = tmp_path / "schema.sql"
    tree.write_text(NEW)
    assert _drift(fresh_database, tree) == [
        (DriftType.CONSTRAINT_MISMATCH.value, "public.tb_node.uq_node_name"),
        (DriftType.EXTRA_INDEX.value, "public.tb_node.ux_node"),
        (DriftType.MISSING_INDEX.value, "public.tb_node.ux_node"),
    ]


def test_the_diff_from_the_database_rebuilds_both_keys(fresh_database: str, tmp_path: Path) -> None:
    _built(fresh_database, OLD)
    tree = tmp_path / "schema.sql"
    tree.write_text(NEW)
    changes = platform.diff(fresh_database, tree).changes
    assert sorted(type(c).__name__ for c in changes) == sorted(
        t.__name__
        for t in (IndexDropped, IndexAdded, UniqueConstraintDropped, UniqueConstraintAdded)
    )
