"""`confiture migrate squash` and `migrate squash-ledger` from the command line (#539)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.migrator import MigratorSession

pytestmark = pytest.mark.integration

runner = CliRunner()

MIGRATIONS = {
    "20260101000000_users": ("CREATE TABLE users (id int PRIMARY KEY);\n", "DROP TABLE users;\n"),
    "20260102000000_email": (
        "ALTER TABLE users ADD COLUMN email text;\n",
        "ALTER TABLE users DROP COLUMN email;\n",
    ),
}
THROUGH = "20260102000000"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project the squash runs in: it asks this project's db/environments/, never the repo's."""
    monkeypatch.chdir(tmp_path)
    migrations = tmp_path / "db/migrations"
    migrations.mkdir(parents=True)
    for stem, (up, down) in MIGRATIONS.items():
        (migrations / f"{stem}.up.sql").write_text(up)
        (migrations / f"{stem}.down.sql").write_text(down)
    schema = tmp_path / "db/schema"
    schema.mkdir()
    (schema / "users.sql").write_text("CREATE TABLE users (id int PRIMARY KEY, email text);\n")
    return tmp_path


def _config(project: Path, url: str, name: str) -> Path:
    path = project / f"{name}.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": name,
                "database_url": url,
                "include_dirs": [str(project / "db/schema")],
            }
        )
    )
    return path


def _cli(argv: list[str]):
    return runner.invoke(app, [*argv, "--format", "json"])


def test_squash_writes_the_baseline(project: Path, test_db_url: str) -> None:
    config = _config(project, test_db_url, "local")

    result = _cli(
        [
            "migrate",
            "squash",
            "--through",
            THROUGH,
            "--config",
            str(config),
            "--migrations-dir",
            str(project / "db/migrations"),
        ]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["versions"] == ["20260101000000", THROUGH]
    assert payload["environments"] == []
    assert payload["dry_run"] is False
    assert Path(payload["baseline"]).exists()
    assert len(list((project / "db/migrations/archive").iterdir())) == 4


def test_a_dry_run_writes_nothing(project: Path, test_db_url: str) -> None:
    config = _config(project, test_db_url, "local")

    result = _cli(
        [
            "migrate",
            "squash",
            "--through",
            THROUGH,
            "--config",
            str(config),
            "--migrations-dir",
            str(project / "db/migrations"),
            "--dry-run",
        ]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["dry_run"] is True
    assert not (project / "db/migrations/archive").exists()


def test_from_build_uses_the_config_s_tree(project: Path, test_db_url: str) -> None:
    config = _config(project, test_db_url, "local")

    result = _cli(
        [
            "migrate",
            "squash",
            "--through",
            THROUGH,
            "--config",
            str(config),
            "--migrations-dir",
            str(project / "db/migrations"),
            "--from-build",
            "--dry-run",
        ]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["source"] == "build"


def test_squash_ledger_records_the_baseline(
    project: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    migrations = project / "db/migrations"
    env_url = fresh_database_factory("confiture_sq_cli")
    with MigratorSession(None, migrations, database_url_override=env_url) as session:
        assert session.up().success
    assert (
        _cli(
            [
                "migrate",
                "squash",
                "--through",
                THROUGH,
                "--config",
                str(_config(project, test_db_url, "local")),
                "--migrations-dir",
                str(migrations),
            ]
        ).exit_code
        == 0
    )

    result = _cli(
        [
            "migrate",
            "squash-ledger",
            "--config",
            str(_config(project, env_url, "production")),
            "--migrations-dir",
            str(migrations),
        ]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert (payload["recorded"], payload["dry_run"]) == (["20260102000001"], False)
    with psycopg.connect(env_url) as conn:
        archived = conn.execute(
            "SELECT count(*) FROM tb_confiture WHERE archived_into = '20260102000001'"
        ).fetchone()
    assert archived == (2,)


def test_squash_refuses_an_environment_that_has_not_caught_up(
    project: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    behind = fresh_database_factory("confiture_sq_behind")
    (project / "db/environments").mkdir()
    _config(project, behind, "staging").rename(project / "db/environments/staging.yaml")

    result = _cli(
        [
            "migrate",
            "squash",
            "--through",
            THROUGH,
            "--config",
            str(_config(project, test_db_url, "local")),
            "--migrations-dir",
            str(project / "db/migrations"),
        ]
    )

    assert result.exit_code == 5
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "VALID_009"
    assert "staging" in error["message"]
