"""An INVALID index is read as one, and rebuilt rather than taken as present (#689).

A failed ``CREATE INDEX CONCURRENTLY`` leaves its index behind with
``indisvalid = false``: it enforces nothing — a unique one lets duplicates in —
and serves no query, and ``CREATE … IF NOT EXISTS`` skips it. Read as present,
it is drift nobody reports. The differ already has the remedy for an index that
is not what the tree says: drop it concurrently and create it again.
"""

from pathlib import Path

import psycopg
import pytest

from confiture import platform
from confiture.core import live_catalog
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.drift import DriftSeverity, DriftType, SchemaDriftDetector
from confiture.core.schema_change import IndexAdded, IndexDropped

pytestmark = pytest.mark.integration

TABLE = "CREATE TABLE tb_item (id int PRIMARY KEY, name text, qty int);\n"
UNIQUE = "CREATE UNIQUE INDEX ux_item_name ON tb_item (name);\n"
EXPRESSION = "CREATE INDEX ix_item_ratio ON tb_item ((100 / qty));\n"


def _run(url: str, *statements: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        for statement in statements:
            conn.execute(statement)


def _left_invalid(url: str, statement: str) -> None:
    """Run a ``CREATE INDEX CONCURRENTLY`` that fails, leaving its index INVALID."""
    with psycopg.connect(url, autocommit=True) as conn, pytest.raises(psycopg.Error):
        conn.execute(statement)


@pytest.fixture
def invalid_unique(fresh_database: str) -> str:
    """``ux_item_name`` exists INVALID: two rows share a name."""
    _run(fresh_database, TABLE, "INSERT INTO tb_item VALUES (1, 'a', 1), (2, 'a', 2)")
    _left_invalid(fresh_database, UNIQUE.replace("INDEX", "INDEX CONCURRENTLY"))
    return fresh_database


@pytest.fixture
def invalid_expression(fresh_database: str) -> str:
    """``ix_item_ratio`` exists INVALID: a row divides by zero."""
    _run(fresh_database, TABLE, "INSERT INTO tb_item VALUES (1, 'a', 0)")
    _left_invalid(fresh_database, EXPRESSION.replace("INDEX", "INDEX CONCURRENTLY"))
    return fresh_database


def _indexes(url: str) -> dict[str, bool]:
    with psycopg.connect(url) as conn:
        model = live_catalog.read(conn, schemas=["public"])
    (table,) = model.tables.values()
    return {index.name or "": index.valid for index in table.indexes}


def _drift(url: str, tree: Path) -> list:
    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn).compare_with_schema_file(str(tree))
    return sorted(report.drift_items, key=lambda item: item.drift_type.value)


def _tree(tmp_path: Path, sql: str) -> Path:
    tree = tmp_path / "schema.sql"
    tree.write_text(sql)
    return tree


def test_the_live_reader_reads_validity(invalid_unique: str) -> None:
    assert _indexes(invalid_unique) == {"tb_item_pkey": True, "ux_item_name": False}


def test_every_index_listing_reads_it(invalid_unique: str) -> None:
    with psycopg.connect(invalid_unique) as conn:
        listed = live_catalog.indexes(conn, ["public"])
    assert {i.name: i.valid for found in listed.values() for i in found}["ux_item_name"] is False
    with psycopg.connect(invalid_unique) as conn:
        assert live_catalog.invalid_indexes(conn, ["public"]) == {("public", "ux_item_name")}


def test_a_partitioned_parent_index_built_on_only_reads_as_valid(fresh_database: str) -> None:
    """``ON ONLY`` leaves the parent's index invalid until every partition attaches: by design."""
    _run(
        fresh_database,
        "CREATE TABLE tb_log (at int) PARTITION BY RANGE (at)",
        "CREATE INDEX ix_log_at ON ONLY tb_log (at)",
    )
    with psycopg.connect(fresh_database) as conn:
        assert live_catalog.invalid_indexes(conn, ["public"]) == set()


def test_drift_reports_the_invalid_unique_index_as_a_critical_pair(
    invalid_unique: str, tmp_path: Path
) -> None:
    extra, missing = _drift(invalid_unique, _tree(tmp_path, TABLE + UNIQUE))

    assert (extra.drift_type, missing.drift_type) == (
        DriftType.EXTRA_INDEX,
        DriftType.MISSING_INDEX,
    )
    assert missing.severity is DriftSeverity.CRITICAL
    assert "INVALID" in missing.message
    assert extra.object_name == missing.object_name == "public.tb_item.ux_item_name"


def test_an_invalid_plain_index_is_a_warning_pair(invalid_expression: str, tmp_path: Path) -> None:
    _, missing = _drift(invalid_expression, _tree(tmp_path, TABLE + EXPRESSION))

    assert missing.severity is DriftSeverity.WARNING
    assert "INVALID" in missing.message


def test_the_diff_from_the_database_rebuilds_it(invalid_unique: str, tmp_path: Path) -> None:
    changes = platform.diff(invalid_unique, _tree(tmp_path, TABLE + UNIQUE)).changes

    assert [type(c) for c in changes] == [IndexDropped, IndexAdded]
    sql = "".join(DifferSQLGenerator().generate_up(c) or "" for c in changes)
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in sql
    assert "CREATE UNIQUE INDEX CONCURRENTLY" in sql


def test_an_unnamed_tree_index_is_created_under_the_live_name(
    invalid_expression: str, tmp_path: Path
) -> None:
    """Dropped and never re-created would be worse than left invalid."""
    tree = _tree(tmp_path, TABLE + "CREATE INDEX ON tb_item ((100 / qty));\n")

    changes = platform.diff(invalid_expression, tree).changes

    [added] = [c for c in changes if isinstance(c, IndexAdded)]
    assert added.index.name == "ix_item_ratio"
    assert "CREATE INDEX CONCURRENTLY" in (DifferSQLGenerator().generate_up(added) or "")


def test_a_valid_index_is_no_drift(fresh_database: str, tmp_path: Path) -> None:
    _run(fresh_database, TABLE + UNIQUE)

    assert _drift(fresh_database, _tree(tmp_path, TABLE + UNIQUE)) == []


def _preflight(migrations: Path, against: str) -> dict:
    import json

    from typer.testing import CliRunner

    from confiture.cli.main import app

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "preflight",
            "--migrations-dir",
            str(migrations),
            "--against",
            against,
            "--format",
            "json",
        ],
    )
    # 0 = clean, 7 = a preflight finding; the issues are the subject here.
    assert result.exit_code in (0, 7), result.output
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("statement", "warned"),
    [
        ("CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_item_name ON tb_item (name);", True),
        ("CREATE UNIQUE INDEX IF NOT EXISTS ux_item_name ON public.tb_item (name);", True),
        ("CREATE UNIQUE INDEX IF NOT EXISTS ux_other ON tb_item (name);", False),
    ],
)
def test_preflight_names_an_if_not_exists_the_invalid_index_would_skip(
    invalid_unique: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    statement: str,
    warned: bool,
) -> None:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "20260401000001_ix.up.sql").write_text(statement)
    (migrations / "20260401000001_ix.down.sql").write_text("SELECT 1;")

    payload = _preflight(migrations, invalid_unique)

    found = [i for i in payload["issues"] if i["code"] == "PFLIGHT_INVALID_INDEX"]
    assert bool(found) is warned
    if warned:
        assert found[0]["severity"] == "warning"
        assert "ux_item_name" in found[0]["message"]
        assert "INVALID" in found[0]["message"]


def test_an_invalid_matview_index_is_read_but_not_compared_yet(
    fresh_database: str, tmp_path: Path
) -> None:
    """Tracked in #690: a matview's indexes compare only through the view's equality."""
    view = "CREATE MATERIALIZED VIEW mv_item AS SELECT id, qty FROM tb_item;\n"
    index = "CREATE INDEX ix_mv_ratio ON mv_item ((100 / qty));\n"
    _run(fresh_database, TABLE, "INSERT INTO tb_item VALUES (1, 'a', 0)", view)
    _left_invalid(fresh_database, index.replace("INDEX", "INDEX CONCURRENTLY"))

    with psycopg.connect(fresh_database) as conn:
        assert live_catalog.invalid_indexes(conn, ["public"]) == {("public", "ix_mv_ratio")}
    assert _drift(fresh_database, _tree(tmp_path, TABLE + view + index)) == []
