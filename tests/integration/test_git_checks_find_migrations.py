"""The git checks count a migration where ``migrate up`` would run it (#709).

``--require-migration`` and ``--require-grant-migration`` read which files the branch
changed from ``git diff``, whose paths are the repository root's. A migration is one of
them only when it is a file ``migrate up`` lists from ``--migrations-dir`` (cwd-relative,
like the runner's): wherever the project sits in its repository, whatever the directory
is called, never a file the branch deleted or one nested below the directory.

No database: the checks compare two git trees.
"""

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

pytestmark = pytest.mark.integration

_ENV = (
    "name: local\ndatabase_url: postgresql://localhost/nonexistent\ninclude_dirs:\n  - db/schema\n"
)
_TABLE_A = "CREATE TABLE tb_a (id bigint PRIMARY KEY);\n"
_TABLE_B = "CREATE TABLE tb_b (id bigint PRIMARY KEY);\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _project(repo: Path, project: Path, *, migrations: str = "db/migrations") -> None:
    """A repository on `main` whose project at *project* builds `tb_a`, then a `feat` branch."""
    _git(repo, "init", "-q", "-b", "main")
    _write(project / "db/environments/local.yaml", _ENV)
    _write(project / "db/schema/a.sql", _TABLE_A)
    _write(project / migrations / "20250101000000_create_a.up.sql", _TABLE_A)
    _write(project / migrations / "20250101000000_create_a.down.sql", "DROP TABLE tb_a;\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "feat")


def _commit(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "feat")


def _require_migration(project: Path, monkeypatch: pytest.MonkeyPatch, *extra: str) -> dict:
    monkeypatch.chdir(project)
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--require-migration",
            "--base-ref",
            "main",
            "--env",
            "local",
            "--format",
            "json",
            *extra,
        ],
    )
    return json.loads(result.stdout)


def test_a_project_below_the_repository_root_finds_its_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "services" / "api"
    _project(tmp_path, project)
    _write(project / "db/schema/b.sql", _TABLE_B)
    _write(project / "db/migrations/20260101000000_add_b.up.sql", _TABLE_B)
    _commit(tmp_path)

    payload = _require_migration(project, monkeypatch)

    assert payload["status"] == "passed", payload


def test_a_non_default_migrations_dir_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path, tmp_path, migrations="migrations")
    _write(tmp_path / "db/schema/b.sql", _TABLE_B)
    _write(tmp_path / "migrations/20260101000000_add_b.up.sql", _TABLE_B)
    _commit(tmp_path)

    payload = _require_migration(tmp_path, monkeypatch, "--migrations-dir", "migrations")

    assert payload["status"] == "passed", payload


def test_a_deleted_migration_does_not_accompany_a_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path, tmp_path)
    _write(tmp_path / "db/schema/b.sql", _TABLE_B)
    _git(tmp_path, "rm", "-q", "db/migrations/20250101000000_create_a.down.sql")
    _git(tmp_path, "rm", "-q", "db/migrations/20250101000000_create_a.up.sql")
    _commit(tmp_path)

    payload = _require_migration(tmp_path, monkeypatch)

    assert payload["status"] == "failed", payload
    assert payload["new_migration_files"] == []


def test_a_file_nested_below_the_migrations_dir_is_not_a_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`migrate up` lists the directory flat: it would never run this file."""
    _project(tmp_path, tmp_path)
    _write(tmp_path / "db/schema/b.sql", _TABLE_B)
    _write(tmp_path / "db/migrations/archive/20260101000000_add_b.up.sql", _TABLE_B)
    _commit(tmp_path)

    payload = _require_migration(tmp_path, monkeypatch)

    assert payload["status"] == "failed", payload


def _require_grant_migration(project: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.chdir(project)
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--require-grant-migration",
            "--base-ref",
            "main",
            "--format",
            "json",
        ],
    )
    return json.loads(result.stdout)


_GRANT = "GRANT SELECT ON tb_a TO PUBLIC;\n"


def test_a_grant_change_below_the_repository_root_needs_a_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "services" / "api"
    _project(tmp_path, project)
    _write(project / "db/7_grant/a.sql", _GRANT)
    _commit(tmp_path)

    payload = _require_grant_migration(project, monkeypatch)

    assert payload["status"] == "failed", payload


def test_a_grant_carried_by_a_migration_below_the_repository_root_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "services" / "api"
    _project(tmp_path, project)
    _write(project / "db/7_grant/a.sql", _GRANT)
    _write(project / "db/migrations/20260101000000_grant_a.up.sql", _GRANT)
    _commit(tmp_path)

    payload = _require_grant_migration(project, monkeypatch)

    assert payload["status"] == "passed", payload
