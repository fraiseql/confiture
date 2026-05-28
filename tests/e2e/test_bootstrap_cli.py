"""End-to-end tests for ``confiture bootstrap`` (issue #137 part 1)."""

from __future__ import annotations

import json
import textwrap
import uuid
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app


def _drop_e2e_roles() -> None:
    try:
        admin = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
    except psycopg.OperationalError:
        return
    try:
        for role in ("bootstrap_e2e_role",):
            try:
                admin.execute(f"DROP OWNED BY {role} CASCADE")
            except psycopg.Error:
                pass
            try:
                admin.execute(f'DROP ROLE IF EXISTS "{role}"')
            except psycopg.Error:
                pass
    finally:
        admin.close()


@pytest.fixture()
def bootstrap_db() -> str:
    """Throwaway database connectable as the local superuser."""
    _drop_e2e_roles()
    db_name = f"confiture_boot_e2e_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
        admin.execute(f'CREATE DATABASE "{db_name}"')
        admin.close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
    db_url = f"postgresql://localhost/{db_name}"
    try:
        yield db_url
    finally:
        _drop_e2e_roles()
        try:
            admin = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
            admin.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            admin.close()
        except psycopg.OperationalError:
            pass


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


@pytest.mark.integration
def test_check_exits_1_when_drift_exists(bootstrap_db: str, tmp_path: Path) -> None:
    """`bootstrap --check` exits 1 when the migrator role is missing."""
    cfg = _write_env_config(tmp_path, bootstrap_db)
    result = CliRunner().invoke(app, ["bootstrap", "--check", "--config", str(cfg)])
    assert result.exit_code == 1, result.output
    assert "drift" in result.output.lower()
    assert "create_role" in result.output


@pytest.mark.integration
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


@pytest.mark.integration
def test_dry_run_prints_sql(bootstrap_db: str, tmp_path: Path) -> None:
    cfg = _write_env_config(tmp_path, bootstrap_db)
    result = CliRunner().invoke(app, ["bootstrap", "--dry-run", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "CREATE ROLE" in result.output


@pytest.mark.integration
def test_check_emits_json(bootstrap_db: str, tmp_path: Path) -> None:
    cfg = _write_env_config(tmp_path, bootstrap_db)
    result = CliRunner().invoke(
        app, ["bootstrap", "--check", "--config", str(cfg), "--format", "json"]
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "check"
    assert payload["drift"] is True
    assert any(s["label"] == "create_role" for s in payload["plan"]["steps"])


@pytest.mark.integration
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
    # `error_console` writes to stderr; CliRunner mixes stderr into output
    # by default in older Typer versions and into result.stderr otherwise.
    # Just assert the exit code — the message is documented elsewhere.
    result = CliRunner().invoke(app, ["bootstrap", "--check", "--config", str(cfg)])
    assert result.exit_code == 2, result.output
