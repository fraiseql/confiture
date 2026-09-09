"""What the build reads: each file once, and the same order it read yesterday.

Two overlapping include patterns used to select the same file twice: the schema
carried its text twice, ``build_001`` reported the file as its own duplicate,
and ``--fail-on-duplicates`` refused to build.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.builder import SchemaBuilder

runner = CliRunner()


def _overlapping_project(tmp_path: Path) -> Path:
    """A one-file tree whose include patterns both match that file."""
    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True)
    (schema_dir / "10_t.sql").write_text("CREATE TABLE t (id int);\n")

    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - path: {schema_dir}
    include:
      - "**/*.sql"
      - "*.sql"
build:
  validate_comments:
    enabled: false
""")
    return tmp_path


def test_overlapping_include_patterns_select_once(tmp_path: Path) -> None:
    """A file matched by two include patterns is selected — and built — once."""
    project = _overlapping_project(tmp_path)

    builder = SchemaBuilder(env="local", project_dir=project)
    files = builder.find_sql_files()

    assert len(files) == 1
    assert builder.build().count("CREATE TABLE t (id int);") == 1


def test_overlapping_include_patterns_are_not_a_duplicate_definition(tmp_path: Path) -> None:
    """``build_001`` no longer reports a file as its own duplicate."""
    project = _overlapping_project(tmp_path)

    result = runner.invoke(
        app,
        ["lint", "--env", "local", "--project-dir", str(project), "--format", "json"],
    )

    payload = json.loads(result.stdout)
    codes = [item["rule_id"] for item in payload["violations"]["items"]]
    assert "build_001" not in codes
    assert payload["tables_checked"] == 1
    assert result.exit_code == 0


def test_overlapping_include_patterns_pass_the_duplicate_gate(tmp_path: Path) -> None:
    """``build --fail-on-duplicates`` builds instead of refusing on a phantom."""
    project = _overlapping_project(tmp_path)
    output = tmp_path / "schema.sql"

    result = runner.invoke(
        app,
        [
            "build",
            "--env",
            "local",
            "--project-dir",
            str(project),
            "--output",
            str(output),
            "--fail-on-duplicates",
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
    assert output.read_text().count("CREATE TABLE t (id int);") == 1


def _provenance_project(tmp_path: Path) -> Path:
    """Two entries, three files, and no two files selected the same way."""
    (tmp_path / "db" / "a").mkdir(parents=True)
    (tmp_path / "db" / "b").mkdir(parents=True)
    (tmp_path / "db" / "a" / "00_first.sql").write_text("SELECT 1;\n")
    (tmp_path / "db" / "b" / "00_zero.sql").write_text("SELECT 2;\n")
    (tmp_path / "db" / "b" / "99_last.sql").write_text("SELECT 3;\n")

    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - path: {tmp_path / "db" / "a"}
    order: 20
  - path: {tmp_path / "db" / "b"}
    order: 10
    recursive: false
    include:
      - "9*.sql"
      - "0*.sql"
build:
  validate_comments:
    enabled: false
""")
    return tmp_path


def test_selection_carries_provenance(tmp_path: Path) -> None:
    """Each selected file names the entry, the order and the pattern that found it."""
    project = _provenance_project(tmp_path)
    builder = SchemaBuilder(env="local", project_dir=project)

    selected = builder._select()

    assert [
        (record.path.name, record.entry.name, record.order, record.pattern) for record in selected
    ] == [
        ("00_first.sql", "a", 20, "**/*.sql"),
        ("00_zero.sql", "b", 10, "0*.sql"),
        ("99_last.sql", "b", 10, "9*.sql"),
    ]


def test_find_sql_files_projects_the_selection(tmp_path: Path) -> None:
    """``find_sql_files`` is the paths of ``_select``, in the same order."""
    project = _provenance_project(tmp_path)
    builder = SchemaBuilder(env="local", project_dir=project)

    assert builder.find_sql_files() == [record.path for record in builder._select()]
