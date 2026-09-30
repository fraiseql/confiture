"""`migrate validate --check-path-reads`: a migration that reads a schema file (#540).

A replay installs the file's current text, not the one the migration shipped
with, and the file can never be renamed again (#538). So a new migration that
reads one fails the gate. Migrations outside the git scope (`--since`,
`--base-ref`, `--staged`) are reported as warnings: they are history.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

HEADER = "from pathlib import Path\nfrom confiture.models.migration import Migration\n"
SCHEMA = 'SCHEMA = Path(__file__).resolve().parent.parent / "schema"'


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    for directory in ("db/schema/functions", "db/migrations", "tests/fixtures"):
        (root / directory).mkdir(parents=True)
    (root / "pyproject.toml").write_text("")
    for name in ("a.sql", "b.sql"):
        (root / "db/schema/functions" / name).write_text("SELECT 1;\n")
    (root / "tests/fixtures/rows.csv").write_text("id\n1\n")
    return root


def _migration(root: Path, version: str, module_level: str, up_body: str) -> Path:
    body = "\n".join("        " + line for line in up_body.splitlines())
    path = root / "db/migrations" / f"{version}_m.py"
    path.write_text(
        f"{HEADER}\n{module_level}\n\nclass M(Migration):\n    def up(self) -> None:\n{body}\n"
    )
    return path


def _validate(root: Path, *extra: str) -> tuple[int, dict]:
    previous = Path.cwd()
    os.chdir(root)
    try:
        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--check-path-reads",
                "--migrations-dir",
                "db/migrations",
                "--format",
                "json",
                *extra,
            ],
        )
    finally:
        os.chdir(previous)
    try:
        return result.exit_code, json.loads(result.stdout)
    except json.JSONDecodeError:  # pragma: no cover - diagnostic path
        pytest.fail(f"non-JSON stdout (exit {result.exit_code}):\n{result.output}")


def _files(entries: list[dict]) -> list[str]:
    return [entry["file"] for entry in entries]


def test_sql_embedded_as_constants_is_clean(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _migration(root, "20260101000000", 'DDL = "CREATE TABLE t (id int)"', "self.execute(DDL)")

    code, payload = _validate(root)

    assert code == 0
    assert payload["scanned"] == 1
    assert payload["violations"] == []


def test_a_schema_file_read_by_path_fails_naming_it(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _migration(
        root,
        "20260101000000",
        "",
        'self.execute((Path(__file__).parent.parent / "schema" / "functions" / "a.sql").read_text())',
    )

    code, payload = _validate(root)

    assert code == 1
    (violation,) = payload["violations"]
    assert violation["file"] == "db/schema/functions/a.sql"
    assert violation["migration"] == "db/migrations/20260101000000_m.py"
    assert violation["line"] == 8


def test_paths_from_a_module_tuple_read_in_a_loop_are_one_finding_each(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _migration(
        root,
        "20260101000000",
        f'{SCHEMA}\nFILES = ("functions/a.sql", "functions/b.sql")',
        "for f in FILES:\n    self.execute((SCHEMA / f).read_text())",
    )

    code, payload = _validate(root)

    assert code == 1
    assert _files(payload["violations"]) == [
        "db/schema/functions/a.sql",
        "db/schema/functions/b.sql",
    ]


def test_a_file_outside_the_schema_directories_is_not_flagged(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _migration(root, "20260101000000", "", 'Path("tests/fixtures/rows.csv").read_text()')

    code, payload = _validate(root)

    assert code == 0
    assert payload["scanned"] == 1
    assert payload["violations"] == []


def test_the_schema_directories_are_the_ddl_dirs(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _migration(root, "20260101000000", "", 'Path("tests/fixtures/rows.csv").read_text()')

    code, payload = _validate(root, "--ddl-dir", "tests/fixtures")

    assert code == 1
    assert _files(payload["violations"]) == ["tests/fixtures/rows.csv"]


def test_a_path_the_file_does_not_fix_is_a_warning_with_the_reason(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _migration(root, "20260101000000", "", "for f in self.files():\n    Path(f).read_text()")

    code, payload = _validate(root)

    assert code == 0
    (warning,) = payload["unresolved"]
    assert warning["migration"] == "db/migrations/20260101000000_m.py"
    assert "`f`" in warning["reason"]


# ── git scope: existing offenders are history ────────────────────────────────


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _committed(tmp_path: Path) -> Path:
    """A repository whose first commit holds one migration that reads a schema file."""
    root = _project(tmp_path)
    _git(root, "init")
    _git(root, "config", "user.email", "t@t.com")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "tag.gpgsign", "false")
    _migration(root, "20260101000000", "", 'Path("db/schema/functions/a.sql").read_text()')
    _git(root, "add", ".")
    _git(root, "commit", "-m", "old")
    _git(root, "tag", "base")
    return root


def test_an_offender_outside_the_scope_is_reported_and_does_not_fail(tmp_path: Path) -> None:
    root = _committed(tmp_path)
    _migration(root, "20260201000000", 'DDL = "SELECT 1"', "self.execute(DDL)")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "new")

    code, payload = _validate(root, "--since", "base")

    assert code == 0
    assert payload["violations"] == []
    (legacy,) = payload["out_of_scope"]
    assert legacy["migration"] == "db/migrations/20260101000000_m.py"
    assert legacy["file"] == "db/schema/functions/a.sql"


def test_a_new_offender_inside_the_scope_fails(tmp_path: Path) -> None:
    root = _committed(tmp_path)
    _migration(root, "20260201000000", "", 'Path("db/schema/functions/b.sql").read_text()')
    _git(root, "add", ".")
    _git(root, "commit", "-m", "new")

    code, payload = _validate(root, "--since", "base")

    assert code == 1
    assert _files(payload["violations"]) == ["db/schema/functions/b.sql"]
    assert _files(payload["out_of_scope"]) == ["db/schema/functions/a.sql"]


def test_without_a_scope_every_offender_fails(tmp_path: Path) -> None:
    root = _committed(tmp_path)

    code, payload = _validate(root)

    assert code == 1
    assert _files(payload["violations"]) == ["db/schema/functions/a.sql"]


def test_the_text_report_names_the_migration_and_the_file(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _migration(root, "20260101000000", "", 'Path("db/schema/functions/a.sql").read_text()')
    previous = Path.cwd()
    os.chdir(root)
    try:
        result = runner.invoke(
            app,
            ["migrate", "validate", "--check-path-reads", "--migrations-dir", "db/migrations"],
            terminal_width=200,
        )
    finally:
        os.chdir(previous)

    assert result.exit_code == 1
    assert "db/migrations/20260101000000_m.py:8 reads db/schema/functions/a.sql" in result.stdout
    assert "module constant" in result.stdout


def test_a_migration_archived_by_a_squash_is_not_read(tmp_path: Path) -> None:
    """``migrate squash`` moves it to ``archive/``, out of the migrations the check reads."""
    root = _project(tmp_path)
    migration = _migration(
        root, "20260101000000", "", 'Path("db/schema/functions/a.sql").read_text()'
    )
    (root / "db/migrations/archive").mkdir()
    migration.rename(root / "db/migrations/archive" / migration.name)

    code, payload = _validate(root)

    assert code == 0
    assert payload["scanned"] == 0
