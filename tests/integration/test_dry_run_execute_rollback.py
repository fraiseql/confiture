"""``migrate up --dry-run-execute`` never commits (ENG-01).

The CLI used to run the analysis, ask for confirmation, then fall through into
its *own* apply loop — the one that commits. The SAVEPOINT existed only in the
library session, which the CLI did not call.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()
VERSION = "20260906000003"


def _migrations(tmp_path: Path) -> Path:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / f"{VERSION}_create_gizmos.up.sql").write_text(
        "CREATE TABLE gizmos (id INT PRIMARY KEY);\n"
    )
    (migrations / f"{VERSION}_create_gizmos.down.sql").write_text("DROP TABLE gizmos;\n")
    return migrations


def _state(url: str) -> tuple[bool, int]:
    with psycopg.connect(url) as conn:
        exists = conn.execute("SELECT to_regclass('public.gizmos') IS NOT NULL").fetchone()[0]
        ledger = conn.execute(
            "SELECT count(*) FROM tb_confiture WHERE version = %s", (VERSION,)
        ).fetchone()[0]
    return exists, ledger


@pytest.mark.integration
def test_confirmed_dry_run_execute_commits_nothing(
    clean_test_db, test_db_url: str, tmp_path: Path
) -> None:
    migrations = _migrations(tmp_path)

    result = runner.invoke(
        app,
        [
            "migrate",
            "up",
            "--dry-run-execute",
            "--database-url",
            test_db_url,
            "--migrations-dir",
            str(migrations),
        ],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert "rolled back" in result.output.lower()
    assert _state(test_db_url) == (False, 0)


@pytest.mark.integration
def test_yes_skips_the_prompt_and_still_commits_nothing(
    clean_test_db, test_db_url: str, tmp_path: Path
) -> None:
    migrations = _migrations(tmp_path)

    result = runner.invoke(
        app,
        [
            "migrate",
            "up",
            "--dry-run-execute",
            "--yes",
            "--database-url",
            test_db_url,
            "--migrations-dir",
            str(migrations),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Proceed with real execution" not in result.output
    assert _state(test_db_url) == (False, 0)
