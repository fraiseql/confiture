"""``preflight --against`` names the large tables the pending migrations touch.

This is what ``migrate estimate`` was for, folded where the operator already looks
``estimate`` read ``pg_class`` by ``relname`` alone, listed only
``public`` and printed an unanalysed table as "0 rows, Standard migration OK"; on
printoptim's own database the only two tables past its threshold were outside
``public``. The estimate is read from the ``--against`` target before the replay,
as the other schema facts are, and it is qualified.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.large_tables import LARGE_TABLE_THRESHOLD

pytestmark = pytest.mark.integration

_MIGRATION = """\
ALTER TABLE tenant.tb_stat ADD COLUMN note text;
ALTER TABLE app.tb_small ADD COLUMN note text;
ALTER TABLE app.tb_fresh ADD COLUMN note text;
CREATE TABLE app.tb_new (id int);
CREATE FUNCTION app.fn() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;
"""


@pytest.fixture
def target(fresh_database: str) -> str:
    """``tenant.tb_stat`` past the threshold, ``app.tb_small`` under it, ``app.tb_fresh``
    never analysed — and a ``public.tb_stat`` so a lookup by name alone is wrong."""
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA tenant")
        conn.execute("CREATE SCHEMA app")
        conn.execute("CREATE TABLE tenant.tb_stat (id int)")
        conn.execute(
            "INSERT INTO tenant.tb_stat SELECT generate_series(1, %s)", (LARGE_TABLE_THRESHOLD,)
        )
        conn.execute("CREATE TABLE public.tb_stat (id int)")
        conn.execute("CREATE TABLE app.tb_small (id int)")
        conn.execute("INSERT INTO app.tb_small SELECT generate_series(1, 10)")
        conn.execute("ANALYZE tenant.tb_stat, public.tb_stat, app.tb_small")
        conn.execute("CREATE TABLE app.tb_fresh (id int)")
    return fresh_database


def _preflight(tmp_path: Path, dsn: str, *extra: str) -> str:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "20260921120000_touch.up.sql").write_text(_MIGRATION)
    (migrations / "20260921120000_touch.down.sql").write_text("SELECT 1;\n")
    result = CliRunner().invoke(
        app,
        ["migrate", "preflight", "--migrations-dir", str(migrations), "--against", dsn, *extra],
    )
    assert result.exit_code == 0, result.output
    return result.stdout


def test_the_payload_names_each_large_or_unmeasured_table_it_touches(
    tmp_path: Path, target: str
) -> None:
    stdout = _preflight(tmp_path, target, "--format", "json")

    assert json.loads(stdout)["large_tables"] == [
        {"table": "app.tb_fresh", "estimated_rows": None},
        {"table": "tenant.tb_stat", "estimated_rows": LARGE_TABLE_THRESHOLD},
    ]


def test_the_text_report_advises_batching(tmp_path: Path, target: str) -> None:
    stdout = _preflight(tmp_path, target)

    assert "tenant.tb_stat" in stdout
    assert "--batched" in stdout
