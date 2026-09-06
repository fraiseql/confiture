"""End-to-end tests for ``confiture bootstrap`` (issue #137 part 1)."""

from __future__ import annotations

import json
import textwrap
from collections.abc import Generator
from pathlib import Path

import psycopg
import pytest
from tests.conftest import drop_roles
from typer.testing import CliRunner

from confiture.cli.main import app


@pytest.fixture()
def bootstrap_db(
    superuser_db_url: str, fresh_database: str, maintenance_connection: psycopg.Connection
) -> Generator[str, None, None]:
    """Throwaway database, connected as a superuser: the executor creates roles."""
    drop_roles(maintenance_connection, "bootstrap_e2e_role")
    yield fresh_database
    drop_roles(maintenance_connection, "bootstrap_e2e_role")


def _write_env_config(tmp_path: Path, db_url: str) -> Path:
    cfg = tmp_path / "confiture.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            name: bootstrap-e2e
            database_url: {db_url}
            include_dirs: []
            ownership:
              expected_owner: bootstrap_e2e_role
              apply_to:
                - schema: public
              bootstrap_connection_url: {db_url}
            """
        )
    )
    return cfg


def test_check_exits_1_when_drift_exists(bootstrap_db: str, tmp_path: Path) -> None:
    """`bootstrap --check` exits 1 when the migrator role is missing."""
    cfg = _write_env_config(tmp_path, bootstrap_db)
    result = CliRunner().invoke(app, ["bootstrap", "--check", "--config", str(cfg)])
    assert result.exit_code == 1, result.output
    assert "drift" in result.output.lower()
    assert "create_role" in result.output


def test_apply_then_check_exits_0(bootstrap_db: str, tmp_path: Path) -> None:
    """After `--apply`, `--check` finds no drift."""
    cfg = _write_env_config(tmp_path, bootstrap_db)
    runner = CliRunner()
    apply_result = runner.invoke(
        app, ["bootstrap", "--apply", "--all-schemas", "--config", str(cfg)]
    )
    assert apply_result.exit_code == 0, apply_result.output
    assert "applied" in apply_result.output.lower()

    check_result = runner.invoke(app, ["bootstrap", "--check", "--config", str(cfg)])
    assert check_result.exit_code == 0, check_result.output


def test_dry_run_prints_sql(bootstrap_db: str, tmp_path: Path) -> None:
    cfg = _write_env_config(tmp_path, bootstrap_db)
    result = CliRunner().invoke(app, ["bootstrap", "--dry-run", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "CREATE ROLE" in result.output


def test_check_emits_json(bootstrap_db: str, tmp_path: Path) -> None:
    cfg = _write_env_config(tmp_path, bootstrap_db)
    result = CliRunner().invoke(
        app, ["bootstrap", "--check", "--config", str(cfg), "--format", "json"]
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["mode"] == "check"
    assert payload["drift"] is True
    assert any(s["label"] == "create_role" for s in payload["plan"]["steps"])


def test_config_without_bootstrap_url_exits_2(bootstrap_db: str, tmp_path: Path) -> None:
    cfg = tmp_path / "confiture.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            name: bootstrap-e2e
            database_url: {bootstrap_db}
            include_dirs: []
            ownership:
              expected_owner: bootstrap_e2e_role
              apply_to:
                - schema: public
            """
        )
    )
    result = CliRunner().invoke(app, ["bootstrap", "--check", "--config", str(cfg)])
    # Missing bootstrap_connection_url is a config error → exit 5, not the
    # reserved exit 2 (tracking table absent).
    assert result.exit_code == 5, result.output
