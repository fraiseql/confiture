"""A git check that cannot run says why, under its own code and exit status (#686).

``--require-migration`` used to report every failure of the ref read as "the
schema does not parse", and ``--check-drift`` re-raised every failure as a git
error (exit 7), a ``DIFFER_406`` among them. A git failure is a git failure; a
schema the differ refuses is reported by its code.
"""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_ENV = 'database_url: "postgresql://localhost/test"\ninclude_dirs:\n  - db/schema\n'


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository whose first commit declares a table."""
    root = tmp_path / "repo"
    (root / "db" / "environments").mkdir(parents=True)
    (root / "db" / "migrations").mkdir(parents=True)
    (root / "db" / "schema").mkdir(parents=True)
    (root / "db" / "environments" / "local.yaml").write_text(_ENV)
    (root / "confiture.yaml").write_text("name: local\n" + _ENV)
    (root / "db" / "schema" / "b_tb_post.sql").write_text("CREATE TABLE post (id int);\n")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    monkeypatch.chdir(root)
    return root


def _misordered(root: Path) -> None:
    """Commit an index whose file the build reads before the table's."""
    (root / "db" / "schema" / "a_ix_post.sql").write_text("CREATE INDEX ix_post ON post (id);\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "an index read before its table")


def _submodule(root: Path) -> None:
    """Commit a submodule under the include directory: the ref read refuses it."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    _git(root, "update-index", "--add", "--cacheinfo", f"160000,{head},db/schema/vendored")
    _git(root, "commit", "-q", "-m", "a submodule in the schema")


def _validate(*flags: str) -> Any:
    return runner.invoke(
        app,
        ["migrate", "validate", "-c", "confiture.yaml", "--base-ref", "HEAD~1", *flags],
    )


def test_require_migration_reports_a_git_failure_as_one(project: Path) -> None:
    _submodule(project)

    result = _validate("--require-migration", "--format", "json")

    assert result.exit_code == 7, result.output
    assert "does not parse" not in result.output
    assert "submodule" in result.output


def test_require_migration_names_the_differs_code(project: Path) -> None:
    _misordered(project)

    result = _validate("--require-migration", "--format", "json")

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["migration_error"]
    assert error.startswith("DIFFER_406"), error
    assert "does not parse" not in error


def test_require_migration_text_says_the_check_could_not_run(project: Path) -> None:
    _misordered(project)

    result = _validate("--require-migration")

    assert result.exit_code == 1, result.output
    assert "could not run: DIFFER_406" in result.output


def test_check_drift_exits_with_the_differs_own_status(project: Path) -> None:
    _misordered(project)

    result = _validate("--check-drift", "--format", "json")

    assert result.exit_code == 5, result.output
    assert "DIFFER_406" in result.output


def test_drift_and_accompaniment_share_one_differ(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[object] = []

    def drift(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs["differ"])
        return {"passed": True, "changes": []}

    def accompaniment(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs["differ"])
        return {"is_valid": True}

    monkeypatch.setattr("confiture.cli.git_validation.validate_git_drift", drift)
    monkeypatch.setattr(
        "confiture.cli.git_validation.validate_migration_accompaniment", accompaniment
    )

    result = _validate("--check-drift", "--require-migration")

    assert result.exit_code == 0, result.output
    assert len(seen) == 2
    assert seen[0] is seen[1]
