"""``--database-url`` with an explicit ``--config`` replaces the connection only (#825).

The config's own URL points nowhere, so every command here connects through the
flag; its tracking table is ``public.ledger_825`` while the database's
``search_path`` starts with ``app``. A command that drops the config reads and
writes a bare ``tb_confiture`` through ``search_path`` — in ``app``.
"""

import json
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_LEDGER = "public.ledger_825"
_UNREACHABLE = "postgresql://localhost/nonexistent"


@pytest.fixture
def target(fresh_database_factory: Callable[[str], str]) -> str:
    url = fresh_database_factory("confiture_825")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA app")
        dbname = conn.info.dbname
        conn.execute(t"ALTER DATABASE {dbname:i} SET search_path TO app, public")
    return url


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path]:
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True)
    for version, table in (("001", "t_one"), ("002", "t_two"), ("003", "t_three")):
        (migrations / f"{version}_{table}.up.sql").write_text(
            f"CREATE TABLE public.{table} (id int);\n"
        )
        (migrations / f"{version}_{table}.down.sql").write_text(f"DROP TABLE public.{table};\n")
    config = tmp_path / "env.yaml"
    config.write_text(
        f"name: production\ndatabase_url: {_UNREACHABLE}\n"
        f"migration:\n  tracking_table: {_LEDGER}\n  locking:\n    enabled: true\n"
    )
    return config, migrations


def _run(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def _tables(url: str) -> dict[str, list[str]]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT schemaname, tablename FROM pg_tables "
            "WHERE schemaname IN ('app', 'public') ORDER BY 1, 2"
        ).fetchall()
    tables: dict[str, list[str]] = {"app": [], "public": []}
    for schema, table in rows:
        tables[schema].append(table)
    return tables


def _ledger(url: str) -> list[str]:
    with psycopg.connect(url) as conn:
        return [row[0] for row in conn.execute(t"SELECT version FROM public.ledger_825 ORDER BY 1")]


def test_every_command_keeps_the_configs_tracking_table(
    target: str, project: tuple[Path, Path]
) -> None:
    config, migrations = project
    common = ("--config", str(config), "--database-url", target)
    dirs = ("--migrations-dir", str(migrations))

    _run("migrate", "baseline", "--through", "001", *dirs, *common)
    assert _ledger(target) == ["001"]

    _run("migrate", "up", *dirs, *common, "--yes")
    assert _ledger(target) == ["001", "002", "003"]

    current = json.loads(_run("migrate", "current", *common, "--format", "json"))
    assert "003" in json.dumps(current)

    status = json.loads(_run("migrate", "status", *dirs, *common, "--format", "json"))
    assert status["tracking_table"] == _LEDGER
    assert (status["summary"]["applied"], status["summary"]["pending"]) == (3, 0)

    _run("migrate", "down-to", "002", *dirs, *common)
    assert _ledger(target) == ["001", "002"]

    tables = _tables(target)
    assert set(tables["app"]) <= {"confiture_lock_holder"}  # the lock table: #826
    assert {"ledger_825", "ledger_825_steps"} <= set(tables["public"])
    assert "tb_confiture" not in tables["public"]
