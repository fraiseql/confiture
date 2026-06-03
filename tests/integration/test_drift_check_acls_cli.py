"""Integration tests for ``confiture drift --check-acls`` (issue #120).

Drives the Typer CLI end-to-end against a real Postgres instance.
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

_SCHEMA = "acl_cli_test"
_ROLES = ("acl_cli_app",)


@pytest.fixture
def pg_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


@pytest.fixture
def acl_db(pg_url: str) -> Generator[psycopg.Connection, None, None]:
    """Provide a connection with a clean schema/role set."""
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
        cur.execute(f"CREATE SCHEMA {_SCHEMA}")
        for role in _ROLES:
            cur.execute(f"CREATE ROLE {role}")
    conn.commit()

    yield conn

    _cleanup()
    conn.close()


def _write_config(tmp_path: Path, pg_url: str, acls_body: str = "") -> Path:
    """Write a single-env config file (the flat shape ``drift --config`` accepts)."""
    cfg = tmp_path / "confiture.yaml"
    body = textwrap.dedent(
        f"""\
        name: test
        database_url: {pg_url}
        include_dirs: []
        """
    )
    if acls_body:
        body += textwrap.dedent(acls_body)
    cfg.write_text(body)
    return cfg


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_check_acls_exits_1_on_missing_grant(
    tmp_path: Path, acl_db: psycopg.Connection, pg_url: str
) -> None:
    with acl_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_SCHEMA}.tb_foo (id int)")
        cur.execute(f"GRANT SELECT ON {_SCHEMA}.tb_foo TO acl_cli_app")
    acl_db.commit()

    cfg = _write_config(
        tmp_path,
        pg_url,
        f"""
        acls:
          - schema: {_SCHEMA}
            apply_to: ALL_TABLES
            grants:
              - role: acl_cli_app
                privileges: [SELECT, INSERT]
        """,
    )
    result = CliRunner().invoke(app, ["drift", "--check-acls", "--config", str(cfg)])
    assert result.exit_code == 1, result.output
    assert "MISSING_GRANT" in result.output.upper()


def test_check_acls_exits_0_on_full_coverage(
    tmp_path: Path, acl_db: psycopg.Connection, pg_url: str
) -> None:
    with acl_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_SCHEMA}.tb_foo (id int)")
        cur.execute(f"GRANT SELECT, INSERT ON {_SCHEMA}.tb_foo TO acl_cli_app")
    acl_db.commit()

    cfg = _write_config(
        tmp_path,
        pg_url,
        f"""
        acls:
          - schema: {_SCHEMA}
            apply_to: ALL_TABLES
            grants:
              - role: acl_cli_app
                privileges: [SELECT, INSERT]
        """,
    )
    result = CliRunner().invoke(app, ["drift", "--check-acls", "--config", str(cfg)])
    assert result.exit_code == 0, result.output


def test_check_acls_works_without_schema_flag(
    tmp_path: Path, acl_db: psycopg.Connection, pg_url: str
) -> None:
    """Without --schema and with --check-acls, exit is 0 or 1, never 2."""
    cfg = _write_config(
        tmp_path,
        pg_url,
        f"""
        acls:
          - schema: {_SCHEMA}
            apply_to: ALL_TABLES
            grants: []
        """,
    )
    result = CliRunner().invoke(app, ["drift", "--check-acls", "--config", str(cfg)])
    assert result.exit_code in (0, 1), result.output


# ---------------------------------------------------------------------------
# Config guards
# ---------------------------------------------------------------------------


def test_check_acls_without_acls_block_is_config_error(
    tmp_path: Path, acl_db: psycopg.Connection, pg_url: str
) -> None:
    cfg = _write_config(tmp_path, pg_url)  # no acls: block
    result = CliRunner().invoke(app, ["drift", "--check-acls", "--config", str(cfg)])
    # Phase 03: missing required block → ConfigurationError (CONFIG_001 → exit 5)
    assert result.exit_code == 5, result.output


def test_check_acls_without_acls_block_emits_helpful_message(
    tmp_path: Path,
    acl_db: psycopg.Connection,
    pg_url: str,
) -> None:
    """Run as subprocess so the Rich error_console (which caches sys.stderr
    at module import) is observable through normal stream capture."""
    import subprocess

    cfg = _write_config(tmp_path, pg_url)  # no acls: block
    completed = subprocess.run(
        ["confiture", "drift", "--check-acls", "--config", str(cfg)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 5
    combined = completed.stdout + completed.stderr
    assert "acls" in combined.lower()
    assert "requires" in combined.lower()
    # Rich wraps the (long tmp) config path mid-string at the default 80-col
    # width when there's no TTY (e.g. "…/confi\nture.yaml"). Compare with ANSI
    # stripped and whitespace collapsed so the assertion is width-independent
    # (mirrors tests/unit/test_migrate_database_url_flag.py::test_database_url_in_help).
    import re

    _ansi = re.compile(r"\x1b\[[0-9;]*m")
    collapsed = re.sub(r"\s+", "", _ansi.sub("", combined))
    assert re.sub(r"\s+", "", str(cfg)) in collapsed, combined


# ---------------------------------------------------------------------------
# --warn-only — demotes MISSING_GRANT to WARNING (exit 0 if no other critical)
# ---------------------------------------------------------------------------


def test_warn_only_demotes_missing_grant(
    tmp_path: Path, acl_db: psycopg.Connection, pg_url: str
) -> None:
    with acl_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_SCHEMA}.tb_foo (id int)")
        cur.execute(f"GRANT SELECT ON {_SCHEMA}.tb_foo TO acl_cli_app")
    acl_db.commit()

    cfg = _write_config(
        tmp_path,
        pg_url,
        f"""
        acls:
          - schema: {_SCHEMA}
            apply_to: ALL_TABLES
            grants:
              - role: acl_cli_app
                privileges: [SELECT, INSERT]
        """,
    )
    result = CliRunner().invoke(app, ["drift", "--check-acls", "--warn-only", "--config", str(cfg)])
    # MISSING_GRANT becomes WARNING, so without --fail-on-warning the exit is 0.
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# JSON output preserves back-compat shape
# ---------------------------------------------------------------------------


def test_check_acls_json_output_contains_drift_items(
    tmp_path: Path, acl_db: psycopg.Connection, pg_url: str
) -> None:
    with acl_db.cursor() as cur:
        cur.execute(f"CREATE TABLE {_SCHEMA}.tb_foo (id int)")
    acl_db.commit()  # no grants at all

    cfg = _write_config(
        tmp_path,
        pg_url,
        f"""
        acls:
          - schema: {_SCHEMA}
            apply_to: ALL_TABLES
            grants:
              - role: acl_cli_app
                privileges: [SELECT]
        """,
    )
    result = CliRunner().invoke(
        app, ["drift", "--check-acls", "--format", "json", "--config", str(cfg)]
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert "drift_items" in payload
    types = {item["type"] for item in payload["drift_items"]}
    assert "missing_grant" in types
