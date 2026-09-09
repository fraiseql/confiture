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
