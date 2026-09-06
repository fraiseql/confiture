"""``--rebuild-threshold`` comes from config, and an invalid config is an error (Phase 04, Cycle 7).

``migrate status --check-rebuild`` read ``migration.rebuild_threshold`` only in
table mode — and through a plain dict that has no ``.migration``, so never —
while JSON mode hard-coded 5. ``migrate up`` loaded the environment config for
strict mode inside ``except Exception: pass``: an invalid file meant a silently
non-strict run.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from tests.unit._doubles import connection_double, migrator_double, session_double
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.models.results import MigrateUpResult

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True)
    for i in (1, 2, 3):
        (migrations / f"2026010112000{i}_m{i}.up.sql").write_text(f"CREATE TABLE t{i} (id INT);\n")
        (migrations / f"2026010112000{i}_m{i}.down.sql").write_text(f"DROP TABLE t{i};\n")
    (tmp_path / "db" / "environments").mkdir()
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "name: local\ndatabase_url: postgresql://x/y\nmigration:\n  rebuild_threshold: 3\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    return tmp_path


def _status(fmt: str):
    migrator = migrator_double(
        tracking_table_exists=True,
        get_applied_versions=[],
        get_applied_migrations_with_timestamps=[],
    )
    with (
        patch("confiture.core.connection.create_connection", return_value=connection_double()),
        patch("confiture.core.migrator.Migrator", autospec=True, return_value=migrator),
    ):
        return runner.invoke(
            app,
            [
                "migrate",
                "status",
                "-c",
                "db/environments/local.yaml",
                "--check-rebuild",
                "--format",
                fmt,
            ],
        )


def test_json_advisory_uses_the_configured_threshold(project: Path) -> None:
    result = _status("json")
    payload = json.loads(result.stdout)
    reasons = " ".join(payload.get("rebuild_reasons", []))
    assert "threshold of 3" in reasons, payload


def test_table_advisory_uses_the_configured_threshold(project: Path) -> None:
    result = _status("table")
    assert "threshold of 3" in result.output, result.output


def test_invalid_environment_config_fails_migrate_up(project: Path) -> None:
    (project / "db" / "environments" / "bad.yaml").write_text(
        "name: bad\ndatabase_url: postgresql://x/y\nmigration:\n  strict_mode: not-a-bool\n"
    )
    session = session_double()
    session.__enter__.return_value = session
    session.up.return_value = MigrateUpResult(
        success=True, migrations_applied=[], total_execution_time_ms=0
    )
    with patch("confiture.core.migrator.MigratorSession", autospec=True, return_value=session):
        result = runner.invoke(app, ["migrate", "up", "-c", "db/environments/bad.yaml"])

    assert result.exit_code == 5, result.output
    assert "strict_mode" in result.output
    session.up.assert_not_called()
