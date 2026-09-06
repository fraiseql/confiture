"""With ``--format json``, stdout is the payload and nothing else (ENG-11).

Progress and warning lines belong on stderr when the payload is machine-read;
``json.loads(result.stdout)`` must parse without scraping for the first ``{``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _migrations(tmp_path: Path) -> Path:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "20260906000011_widgets.up.sql").write_text("CREATE TABLE widgets (id INT);\n")
    (migrations / "20260906000011_widgets.down.sql").write_text("DROP TABLE widgets;\n")
    return migrations


def _up(url: str, migrations: Path, *extra: str):
    return runner.invoke(
        app,
        [
            "migrate",
            "up",
            "--format",
            "json",
            "--database-url",
            url,
            "--migrations-dir",
            str(migrations),
            *extra,
        ],
    )


@pytest.mark.integration
def test_migrate_up_json_stdout_is_the_payload(
    clean_test_db, test_db_url: str, tmp_path: Path
) -> None:
    migrations = _migrations(tmp_path)

    applied = _up(test_db_url, migrations, "--no-lock")
    assert applied.exit_code == 0, applied.output
    payload = json.loads(applied.stdout)
    assert [m["version"] for m in payload["applied"]] == ["20260906000011"]

    nothing = _up(test_db_url, migrations, "--force" if False else "--no-lock")
    assert nothing.exit_code == 0, nothing.output
    payload = json.loads(nothing.stdout)
    assert payload["success"] is True
    assert payload["applied"] == []


@pytest.mark.integration
def test_build_json_stdout_is_the_payload(clean_test_db, test_db_url: str, tmp_path: Path) -> None:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "10_tables.sql").write_text("CREATE TABLE things (id INT);\n")
    (tmp_path / "db" / "environments").mkdir()
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        f"name: local\ndatabase_url: {test_db_url}\ninclude_dirs:\n  - db/schema\n"
    )

    result = runner.invoke(
        app, ["build", "--env", "local", "--project-dir", str(tmp_path), "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is True


@pytest.mark.integration
def test_migrate_status_connection_warning_goes_to_stderr(tmp_path: Path) -> None:
    migrations = _migrations(tmp_path)
    config = tmp_path / "cfg.yaml"
    config.write_text("name: x\ndatabase_url: postgresql://localhost/nonexistent\n")

    result = runner.invoke(
        app, ["migrate", "status", "-c", str(config), "--migrations-dir", str(migrations)]
    )

    assert result.exit_code == 3, result.output  # fatal: the database is unreachable
    assert "Could not connect" not in result.stdout, result.stdout
    assert "Could not connect" in result.stderr
