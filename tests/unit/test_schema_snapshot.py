"""A schema-history snapshot is the model's wire: the environment's build, as PostgreSQL holds it.

``migrate generate`` writes one beside each migration, and the baseline detector compares
a database with each (``tests/integration/test_baseline_detection.py``). Live mode, which
reads the build back from a scratch server, is the integration suite's.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.schema_model import SchemaModel
from confiture.core.schema_read import read_text
from confiture.core.schema_snapshot import SchemaSnapshotGenerator

SCHEMA = """
CREATE TABLE tb_parent (id bigint PRIMARY KEY);
CREATE TABLE tb_child (id bigint, pid bigint REFERENCES tb_parent) PARTITION BY RANGE (id);
CREATE TABLE tb_child_1 PARTITION OF tb_child FOR VALUES FROM (0) TO (10);
"""


def _project(root: Path, sql: str = SCHEMA) -> Path:
    (root / "db" / "schema").mkdir(parents=True)
    (root / "db" / "schema" / "schema.sql").write_text(sql)
    (root / "db" / "environments").mkdir(parents=True)
    (root / "db" / "environments" / "local.yaml").write_text(
        "name: local\ndatabase_url: postgresql://localhost/nonexistent\ninclude_dirs:\n  - db/schema\n"
    )
    return root


def test_a_snapshot_is_named_by_its_migration(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    path = SchemaSnapshotGenerator(tmp_path / "history").write_snapshot(
        "local", "007", "add_payments", project
    )
    assert path == tmp_path / "history" / "007_add_payments.json"


def test_a_snapshot_is_the_build_as_postgresql_holds_it(tmp_path: Path) -> None:
    """The catalogued model: a partition holds its parent's columns, as a database lists them."""
    project = _project(tmp_path / "project")
    path = SchemaSnapshotGenerator(tmp_path / "history").write_snapshot(
        "local", "001", "init", project
    )
    assert SchemaModel.from_json(path.read_text()) == read_text(SCHEMA).catalogued


def test_a_snapshot_is_the_same_bytes_every_time(tmp_path: Path) -> None:
    project = _project(tmp_path / "project")
    generator = SchemaSnapshotGenerator(tmp_path / "history")
    first = generator.write_snapshot("local", "001", "a", project).read_bytes()
    second = generator.write_snapshot("local", "002", "b", project).read_bytes()
    assert first == second


def test_writing_a_version_again_replaces_its_snapshot(tmp_path: Path) -> None:
    generator = SchemaSnapshotGenerator(tmp_path / "history")
    generator.write_snapshot("local", "001", "init", _project(tmp_path / "one"))
    other = "CREATE TABLE tb_other (id int);"
    path = generator.write_snapshot("local", "001", "init", _project(tmp_path / "two", other))
    assert SchemaModel.from_json(path.read_text()) == read_text(other).catalogued
