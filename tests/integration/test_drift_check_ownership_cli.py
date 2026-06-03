"""Integration tests for ``confiture drift --check-ownership`` (issue #124).

Drives the Typer CLI end-to-end against a real Postgres instance.
Mirrors :mod:`tests.integration.test_drift_check_acls_cli`.
"""

from __future__ import annotations

import json
import os
import textwrap
from collections.abc import Generator
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

_SCHEMA = "own_cli_test"
_ROLES = ("own_cli_migrator", "own_cli_intruder")


@pytest.fixture
def pg_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


@pytest.fixture
def own_db(pg_url: str) -> Generator[psycopg.Connection, None, None]:
    try:
        conn = psycopg.connect(pg_url, autocommit=False)
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")

    def _cleanup() -> None:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
            for role in _ROLES:
                cur.execute(f"DROP ROLE IF EXISTS {role}")
        conn.commit()

    _cleanup()
    with conn.cursor() as cur:
        for role in _ROLES:
            cur.execute(f"CREATE ROLE {role}")
        cur.execute(f"CREATE SCHEMA {_SCHEMA} AUTHORIZATION own_cli_migrator")
        cur.execute("GRANT own_cli_migrator TO current_user")
        cur.execute("GRANT own_cli_intruder TO current_user")
    conn.commit()

    yield conn

    _cleanup()
    conn.close()


def _write_config(tmp_path: Path, pg_url: str, ownership_body: str = "") -> Path:
    cfg = tmp_path / "confiture.yaml"
    body = textwrap.dedent(
        f"""\
        name: test
        database_url: {pg_url}
        include_dirs: []
        """
    )
    if ownership_body:
        body += textwrap.dedent(ownership_body)
    cfg.write_text(body)
    return cfg


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_check_ownership_exits_1_on_wrong_owner(
    tmp_path: Path, own_db: psycopg.Connection, pg_url: str
) -> None:
    with own_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_SCHEMA}.tb_foo (id int)")
        cur.execute(f"ALTER TABLE {_SCHEMA}.tb_foo OWNER TO own_cli_intruder")
    own_db.commit()

    cfg = _write_config(
        tmp_path,
        pg_url,
        f"""
        ownership:
          expected_owner: own_cli_migrator
          apply_to:
            - schema: {_SCHEMA}
              relkinds: [r]
        """,
    )
    result = CliRunner().invoke(app, ["drift", "--check-ownership", "--config", str(cfg)])
    assert result.exit_code == 1, result.output
    assert "WRONG_OWNER" in result.output.upper()


def test_check_ownership_exits_0_on_full_coverage(
    tmp_path: Path, own_db: psycopg.Connection, pg_url: str
) -> None:
    with own_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_SCHEMA}.tb_foo (id int)")
        cur.execute(f"ALTER TABLE {_SCHEMA}.tb_foo OWNER TO own_cli_migrator")
    own_db.commit()

    cfg = _write_config(
        tmp_path,
        pg_url,
        f"""
        ownership:
          expected_owner: own_cli_migrator
          apply_to:
            - schema: {_SCHEMA}
              relkinds: [r]
        """,
    )
    result = CliRunner().invoke(app, ["drift", "--check-ownership", "--config", str(cfg)])
    assert result.exit_code == 0, result.output


def test_check_ownership_without_block_is_config_error(
    tmp_path: Path, own_db: psycopg.Connection, pg_url: str
) -> None:
    cfg = _write_config(tmp_path, pg_url)
    result = CliRunner().invoke(app, ["drift", "--check-ownership", "--config", str(cfg)])
    # Phase 03: missing required block → ConfigurationError (CONFIG_001 → exit 5)
    assert result.exit_code == 5, result.output


# ---------------------------------------------------------------------------
# Composition with --check-acls
# ---------------------------------------------------------------------------


def test_check_ownership_composes_with_check_acls(
    tmp_path: Path, own_db: psycopg.Connection, pg_url: str
) -> None:
    with own_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_SCHEMA}.tb_foo (id int)")
        # Wrong owner AND missing grant
        cur.execute(f"ALTER TABLE {_SCHEMA}.tb_foo OWNER TO own_cli_intruder")
    own_db.commit()

    cfg = _write_config(
        tmp_path,
        pg_url,
        f"""
        ownership:
          expected_owner: own_cli_migrator
          apply_to:
            - schema: {_SCHEMA}
              relkinds: [r]
        acls:
          - schema: {_SCHEMA}
            apply_to: ALL_TABLES
            grants:
              - role: own_cli_migrator
                privileges: [SELECT]
        """,
    )
    result = CliRunner().invoke(
        app,
        ["drift", "--check-ownership", "--check-acls", "--config", str(cfg)],
    )
    assert result.exit_code == 1, result.output
    assert "WRONG_OWNER" in result.output.upper()
    assert "MISSING_GRANT" in result.output.upper()


# ---------------------------------------------------------------------------
# JSON output shape
# ---------------------------------------------------------------------------


def test_check_ownership_json_output_shape(
    tmp_path: Path, own_db: psycopg.Connection, pg_url: str
) -> None:
    with own_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_SCHEMA}.tb_foo (id int)")
        cur.execute(f"ALTER TABLE {_SCHEMA}.tb_foo OWNER TO own_cli_intruder")
    own_db.commit()

    cfg = _write_config(
        tmp_path,
        pg_url,
        f"""
        ownership:
          expected_owner: own_cli_migrator
          apply_to:
            - schema: {_SCHEMA}
              relkinds: [r]
        """,
    )
    result = CliRunner().invoke(
        app,
        ["drift", "--check-ownership", "--format", "json", "--config", str(cfg)],
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["has_drift"] is True
    assert payload["expected_schema_source"] == "ownership"
    items = payload["drift_items"]
    assert any(i["type"] == "wrong_owner" for i in items)
    item = next(i for i in items if i["type"] == "wrong_owner")
    assert item["object"] == f"{_SCHEMA}.tb_foo"
    assert item["expected"] == "own_cli_migrator"
    assert item["actual"] == "own_cli_intruder"
    assert item["severity"] == "critical"
