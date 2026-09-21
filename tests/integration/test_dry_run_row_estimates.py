"""``migrate up --dry-run`` estimates the rows of the table a migration touches, in its schema.

It looked each table up by its bare name, so ``tenant.tb_stat``'s estimate was
whichever ``tb_stat`` the catalogue index gave first — ``public``'s, here.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

pytestmark = pytest.mark.integration


def test_the_estimate_is_the_touched_tables_own(tmp_path: Path, fresh_database: str) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute("CREATE TABLE public.tb_stat (id int)")
        conn.execute("INSERT INTO public.tb_stat SELECT generate_series(1, 3)")
        conn.execute("CREATE SCHEMA tenant")
        conn.execute("CREATE TABLE tenant.tb_stat (id int)")
        conn.execute("INSERT INTO tenant.tb_stat SELECT generate_series(1, 50)")
        conn.execute("ANALYZE public.tb_stat, tenant.tb_stat")
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "20260921120000_note.up.sql").write_text(
        "ALTER TABLE tenant.tb_stat ADD COLUMN note text;\n"
    )
    (migrations / "20260921120000_note.down.sql").write_text(
        "ALTER TABLE tenant.tb_stat DROP COLUMN note;\n"
    )
    config = tmp_path / "confiture.yaml"
    config.write_text(yaml.safe_dump({"database_url": fresh_database}))

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "up",
            "-c",
            str(config),
            "--migrations-dir",
            str(migrations),
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    (migration,) = json.loads(result.stdout)["migrations"]
    assert migration["estimated_rows"] == 50
