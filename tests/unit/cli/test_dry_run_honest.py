"""``migrate up --dry-run`` reports what it knows, not constants (ENG-11).

The summary used to print ``Estimated time: 500ms | Disk: 1.0MB | CPU: 30%`` for
every migration and ``classification: "warning"`` regardless of content, and
always closed with "All migrations appear safe to execute".
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from tests.unit._doubles import connection_double
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()
FABRICATED = ("estimated_duration_ms", "estimated_disk_usage_mb", "estimated_cpu_percent")


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "20260101120000_create_users.up.sql").write_text(
        # Two additive statements — a plain CREATE INDEX would be lock_risky, and rightly so.
        "CREATE TABLE users (id INT PRIMARY KEY);\nALTER TABLE users ADD COLUMN email TEXT;\n"
    )
    (migrations / "20260101120000_create_users.down.sql").write_text("DROP TABLE users;\n")
    (migrations / "20260101130000_drop_legacy.up.sql").write_text("DROP TABLE legacy;\n")
    (migrations / "20260101130000_drop_legacy.down.sql").write_text("SELECT 1;\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    return tmp_path


def _dry_run(*extra: str):
    with (
        patch("confiture.cli.helpers.create_connection", return_value=connection_double()),
        patch(
            "confiture.core.connection.load_config",
            return_value={"database_url": "postgresql://x/y"},
        ),
    ):
        return runner.invoke(app, ["migrate", "up", "--dry-run", "--no-lock", *extra])


def test_json_summary_has_no_fabricated_estimates(project: Path) -> None:
    result = _dry_run("--format", "json")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["statements_analyzed"] == 3
    versions = {m["version"]: m for m in payload["migrations"]}
    assert set(versions) == {"20260101120000", "20260101130000"}
    for migration in payload["migrations"]:
        for key in FABRICATED:
            assert key not in migration, migration
        assert migration["classification"] != "warning"
    assert (
        versions["20260101130000"]["classification"] == "irreversible"
    )  # DROP TABLE per core.change_set
    assert versions["20260101120000"]["statements"] == 2
    assert "estimated_rows" in versions["20260101130000"]
    assert payload["summary"]["unsafe_count"] == 1
    assert payload["summary"]["has_unsafe_statements"] is True


def test_text_summary_does_not_call_a_drop_safe(project: Path) -> None:
    result = _dry_run()

    assert result.exit_code == 0, result.output
    assert "appear safe" not in result.output.lower()
    assert "500ms" not in result.output
    assert "drop_legacy" in result.output
    assert "irreversible" in result.output.lower()
