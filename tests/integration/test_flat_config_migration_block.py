"""A config outside ``db/environments/`` has its whole ``migration:`` block applied (#832).

``migrate up --config c.yaml`` took ``tracking_table`` from the file and dropped every
other setting of the same block: ``view_helpers: auto`` installed nothing and
``strict_mode: true`` was a non-strict run.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.ledger import VIEW_HELPER_SCHEMA

runner = CliRunner()


@pytest.fixture
def flat_project(tmp_path: Path, fresh_database: str) -> Iterator[Path]:
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "20260101000000_widgets.up.sql").write_text(
        "CREATE TABLE widgets (id BIGINT PRIMARY KEY);\n"
    )
    (migrations / "20260101000000_widgets.down.sql").write_text("DROP TABLE widgets;\n")
    (tmp_path / "c.yaml").write_text(
        yaml.safe_dump(
            {
                "database_url": fresh_database,
                "migration": {
                    "tracking_table": "public.ledger_832",
                    "view_helpers": "auto",
                    "strict_mode": True,
                },
            }
        )
    )
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _one(url: str, sql: str) -> object:
    with psycopg.connect(url) as conn:
        row = conn.execute(sql).fetchone()
    return row[0] if row else None


def test_migrate_up_installs_helpers_from_a_flat_config(
    flat_project: Path, fresh_database: str
) -> None:
    result = runner.invoke(app, ["migrate", "up", "--config", "c.yaml"])

    assert result.exit_code == 0, result.output
    assert _one(fresh_database, "SELECT count(*) FROM public.ledger_832") == 1
    assert (
        _one(
            fresh_database,
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            f"WHERE n.nspname = '{VIEW_HELPER_SCHEMA}'",
        )
        or 0
    ) > 0


def test_migrate_up_is_strict_from_a_flat_config(flat_project: Path, fresh_database: str) -> None:
    (flat_project / "db" / "migrations" / "stray.sql").write_text("SELECT 1;\n")

    result = runner.invoke(app, ["migrate", "up", "--config", "c.yaml"])

    assert result.exit_code == 1, result.output
    assert "Strict mode" in result.output
    assert _one(fresh_database, "SELECT to_regclass('public.widgets')") is None
