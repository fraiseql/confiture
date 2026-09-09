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


def golden_project(tmp_path: Path) -> Path:
    """A project shaped like the ones this repository ships.

    Three numbered directories under two ``include_dirs`` entries that are
    listed in an order alphabetical sorting does not agree with, no ``order``
    key and no path-shaped glob — the shape every configuration in this
    repository, in ``examples/`` and in ``db/`` happens to use.
    """
    files = {
        "db/schema/00_common/00_extensions.sql": "CREATE EXTENSION IF NOT EXISTS pgcrypto;\n",
        "db/schema/10_tables/10_users.sql": "CREATE TABLE users (id bigint PRIMARY KEY);\n",
        "db/schema/10_tables/20_orders.sql": "CREATE TABLE orders (id bigint PRIMARY KEY);\n",
        "db/functions/30_functions/10_fn_user.sql": "CREATE FUNCTION fn_user() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;\n",
    }
    for relative, sql in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sql)

    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {tmp_path / "db" / "schema"}
  - {tmp_path / "db" / "functions"}
build:
  validate_comments:
    enabled: false
""")
    return tmp_path


GOLDEN_ORDER = [
    "db/functions/30_functions/10_fn_user.sql",
    "db/schema/00_common/00_extensions.sql",
    "db/schema/10_tables/10_users.sql",
    "db/schema/10_tables/20_orders.sql",
]

GOLDEN_HASH = "a4565bdb1d67710c15945bfb9a5748f3a46228df25afe07802ad2f0e044fc17d"


def test_a_default_project_builds_what_it_built_before(tmp_path: Path) -> None:
    """The compatibility claim of this release, as two literals.

    A project that sets no ``order`` and writes no path-shaped glob selects the
    same files, in the same sequence, with the same schema hash. Nothing that
    changes the meaning of ``order``, of ``**`` or of ``recursive`` may move
    either literal.

    It covers exactly one configuration shape — defaults everywhere. What the
    release measures beyond that shape is a sweep over ``db/`` and
    ``examples/``, not this test.
    """
    project = golden_project(tmp_path)
    builder = SchemaBuilder(env="local", project_dir=project)

    selected = [str(path.relative_to(project)) for path in builder.find_sql_files()]

    assert selected == GOLDEN_ORDER
    assert builder.compute_hash() == GOLDEN_HASH
