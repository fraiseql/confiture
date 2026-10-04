"""Which migration level a database is at: the one comparison, against each snapshot.

A snapshot is the schema model at one migration (``SchemaModel.to_json``), written by
``migrate generate``. The detector compares the live database with each, newest first,
through ``SchemaDiffer.compare_sides`` — the comparison under which a database built from
a tree has no change from it — so a database built from the tree a snapshot was taken of
is an **exact** match. The text detector it replaces reconstructed only tables and
columns from the catalog and compared SQL text with ``difflib``: such a database was at
best a near miss, and ``'{}'::jsonb`` against ``'{}'`` was a difference.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture.core.baseline_detector import BaselineDetector
from confiture.core.schema_snapshot import SchemaSnapshotGenerator

pytestmark = pytest.mark.integration

V1 = """
CREATE TABLE tb_user (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email text NOT NULL UNIQUE,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text CHECK (status IN ('active', 'gone'))
);
CREATE INDEX ON tb_user (lower(email));
"""
V2 = V1 + "CREATE TABLE tb_post (id bigint PRIMARY KEY, fk_user bigint REFERENCES tb_user);\n"
V3 = V2 + "CREATE VIEW v_post AS SELECT id FROM tb_post;\n"


def _project(root: Path, sql: str) -> Path:
    """A project whose `local` environment builds *sql*."""
    schema = root / "db" / "schema"
    schema.mkdir(parents=True, exist_ok=True)
    (schema / "schema.sql").write_text(sql)
    env = root / "db" / "environments"
    env.mkdir(parents=True, exist_ok=True)
    (env / "local.yaml").write_text(
        "name: local\ndatabase_url: postgresql://localhost/nonexistent\ninclude_dirs:\n  - db/schema\n"
    )
    return root


def _snapshots(root: Path, *versions: tuple[str, str]) -> Path:
    """One snapshot per ``(version, sql)``, each written the way `migrate generate` writes it."""
    history = root / "history"
    for version, sql in versions:
        project = _project(root / f"project_{version}", sql)
        SchemaSnapshotGenerator(history).write_snapshot("local", version, f"v{version}", project)
    return history


def _built(make_database: Callable[[str], str], sql: str) -> str:
    url = make_database("confiture_baseline")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql)
    return url


def test_a_database_built_from_a_snapshots_tree_is_an_exact_match(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    history = _snapshots(tmp_path, ("001", V1), ("002", V2), ("003", V3))
    with psycopg.connect(_built(fresh_database_factory, V2)) as conn:
        found = BaselineDetector(history).find_matching_snapshot(conn)

    assert found is not None
    assert (found.version, found.name) == ("002", "v002")


def test_the_newest_of_two_equal_snapshots_is_the_level(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    history = _snapshots(tmp_path, ("001", V1), ("002", V1))
    with psycopg.connect(_built(fresh_database_factory, V1)) as conn:
        found = BaselineDetector(history).find_matching_snapshot(conn)

    assert found is not None and found.version == "002"  # newest first, by design


def test_a_database_no_snapshot_describes_reports_its_closest(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    history = _snapshots(tmp_path, ("001", V1), ("003", V3))
    url = _built(fresh_database_factory, V2)
    detector = BaselineDetector(history, similarity_threshold=1.0)
    with psycopg.connect(url) as conn:
        assert detector.find_matching_snapshot(conn) is None

    assert detector.last_closest is not None
    version, similarity = detector.last_closest
    assert version == "003"
    assert 0 < similarity < 1


def test_a_sparse_history_accepts_the_closest_above_the_threshold(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    history = _snapshots(tmp_path, ("001", V1), ("003", V3))
    url = _built(fresh_database_factory, V2)
    with psycopg.connect(url) as conn:
        found = BaselineDetector(history, similarity_threshold=0.5).find_matching_snapshot(conn)

    assert found is not None and found.version == "003"


def test_a_snapshot_written_as_sql_still_matches(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    """A history written before snapshots were model wire: DDL text, read once."""
    history = tmp_path / "history"
    history.mkdir()
    (history / "001_legacy.sql").write_text(V1)
    with psycopg.connect(_built(fresh_database_factory, V1)) as conn:
        found = BaselineDetector(history).find_matching_snapshot(conn)

    assert found is not None and found.version == "001"


def test_a_live_snapshot_is_the_database_the_tree_builds(
    tmp_path: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    """``--live-snapshot`` reads the tree back from a scratch database: PostgreSQL's model."""
    project = _project(tmp_path / "project", V3)
    path = SchemaSnapshotGenerator(tmp_path / "history").write_snapshot(
        "local", "001", "live", project, database_url=test_db_url
    )
    assert path.name == "001_live.json"
    assert '"source": "catalog"' in path.read_text()

    with psycopg.connect(_built(fresh_database_factory, V3)) as conn:
        found = BaselineDetector(tmp_path / "history").find_matching_snapshot(conn)
    assert found is not None and found.version == "001"
