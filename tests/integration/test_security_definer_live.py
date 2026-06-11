"""Integration tests for the live sec_002 path (issue #161 Phase 03).

Requires a running PostgreSQL instance at CONFITURE_TEST_DB_URL
(default: postgresql://localhost/confiture_test). Skips automatically
when the database is not reachable.

Tests create SECURITY DEFINER fixtures in a dedicated schema, assert
which ones are flagged, then tear everything down.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.libraries.security_definer import Sec002SecurityDefinerSearchPath
from confiture.core.linting.schema_linter import RuleSeverity

# Skip the whole module when pglast isn't installed (not strictly needed for
# the live path, but keeps test-suite intent clean — the live path is part
# of the same rule).
pytest.importorskip("pglast")

_SCRATCH_SCHEMA = "confiture_sec002_test"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SETUP_SQL = f"""
CREATE SCHEMA IF NOT EXISTS {_SCRATCH_SCHEMA};

-- Unpinned SECURITY DEFINER function → should be flagged
CREATE OR REPLACE FUNCTION {_SCRATCH_SCHEMA}.f_unpinned()
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$ BEGIN END $$;

-- Pinned with SET search_path → should NOT be flagged
CREATE OR REPLACE FUNCTION {_SCRATCH_SCHEMA}.f_pinned()
    RETURNS void LANGUAGE plpgsql
    SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$ BEGIN END $$;

-- SECURITY INVOKER (default) → should NOT be flagged
CREATE OR REPLACE FUNCTION {_SCRATCH_SCHEMA}.f_invoker()
    RETURNS void LANGUAGE plpgsql AS $$ BEGIN END $$;

-- Unpinned PROCEDURE → should be flagged
CREATE OR REPLACE PROCEDURE {_SCRATCH_SCHEMA}.p_unpinned()
    LANGUAGE plpgsql SECURITY DEFINER AS $$ BEGIN END $$;

-- Pinned procedure → should NOT be flagged
CREATE OR REPLACE PROCEDURE {_SCRATCH_SCHEMA}.p_pinned()
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
    AS $$ BEGIN END $$;
"""

_TEARDOWN_SQL = f"DROP SCHEMA IF EXISTS {_SCRATCH_SCHEMA} CASCADE;"


@pytest.fixture
def secdef_db(clean_test_db: psycopg.Connection) -> psycopg.Connection:
    """Set up scratch SECURITY DEFINER fixtures, tear down after."""
    conn = clean_test_db
    with conn.cursor() as cur:
        cur.execute(_SETUP_SQL)
    conn.commit()
    yield conn
    with conn.cursor() as cur:
        cur.execute(_TEARDOWN_SQL)
    conn.commit()


# ---------------------------------------------------------------------------
# Cycle 2: live checker directly
# ---------------------------------------------------------------------------


def test_check_live_flags_unpinned_function(secdef_db: psycopg.Connection) -> None:
    rule = Sec002SecurityDefinerSearchPath(severity=RuleSeverity.ERROR)
    violations = rule.check_live(secdef_db, schemas=[_SCRATCH_SCHEMA])
    flagged = {v.object_name for v in violations}
    assert f"{_SCRATCH_SCHEMA}.f_unpinned" in flagged


def test_check_live_flags_unpinned_procedure(secdef_db: psycopg.Connection) -> None:
    rule = Sec002SecurityDefinerSearchPath(severity=RuleSeverity.ERROR)
    violations = rule.check_live(secdef_db, schemas=[_SCRATCH_SCHEMA])
    flagged = {v.object_name for v in violations}
    assert f"{_SCRATCH_SCHEMA}.p_unpinned" in flagged


def test_check_live_does_not_flag_pinned(secdef_db: psycopg.Connection) -> None:
    rule = Sec002SecurityDefinerSearchPath(severity=RuleSeverity.ERROR)
    violations = rule.check_live(secdef_db, schemas=[_SCRATCH_SCHEMA])
    flagged = {v.object_name for v in violations}
    assert f"{_SCRATCH_SCHEMA}.f_pinned" not in flagged
    assert f"{_SCRATCH_SCHEMA}.p_pinned" not in flagged


def test_check_live_does_not_flag_invoker(secdef_db: psycopg.Connection) -> None:
    rule = Sec002SecurityDefinerSearchPath(severity=RuleSeverity.ERROR)
    violations = rule.check_live(secdef_db, schemas=[_SCRATCH_SCHEMA])
    flagged = {v.object_name for v in violations}
    assert f"{_SCRATCH_SCHEMA}.f_invoker" not in flagged


def test_check_live_exact_flagged_set(secdef_db: psycopg.Connection) -> None:
    """Exactly f_unpinned and p_unpinned are flagged, nothing else."""
    rule = Sec002SecurityDefinerSearchPath(severity=RuleSeverity.WARNING)
    violations = rule.check_live(secdef_db, schemas=[_SCRATCH_SCHEMA])
    flagged = {v.object_name for v in violations}
    assert flagged == {
        f"{_SCRATCH_SCHEMA}.f_unpinned",
        f"{_SCRATCH_SCHEMA}.p_unpinned",
    }


def test_check_live_ignore_pattern_excludes(secdef_db: psycopg.Connection) -> None:
    rule = Sec002SecurityDefinerSearchPath(
        ignore=[f"{_SCRATCH_SCHEMA}.f_unpinned"],
        severity=RuleSeverity.WARNING,
    )
    violations = rule.check_live(secdef_db, schemas=[_SCRATCH_SCHEMA])
    flagged = {v.object_name for v in violations}
    assert f"{_SCRATCH_SCHEMA}.f_unpinned" not in flagged
    assert f"{_SCRATCH_SCHEMA}.p_unpinned" in flagged


def test_check_live_procedure_object_type(secdef_db: psycopg.Connection) -> None:
    rule = Sec002SecurityDefinerSearchPath()
    violations = rule.check_live(secdef_db, schemas=[_SCRATCH_SCHEMA])
    proc_violations = [v for v in violations if "p_unpinned" in v.object_name]
    assert len(proc_violations) == 1
    assert proc_violations[0].object_type == "procedure"


def test_check_live_function_object_type(secdef_db: psycopg.Connection) -> None:
    rule = Sec002SecurityDefinerSearchPath()
    violations = rule.check_live(secdef_db, schemas=[_SCRATCH_SCHEMA])
    fn_violations = [v for v in violations if "f_unpinned" in v.object_name]
    assert len(fn_violations) == 1
    assert fn_violations[0].object_type == "function"


def test_check_live_severity_propagated(secdef_db: psycopg.Connection) -> None:
    rule = Sec002SecurityDefinerSearchPath(severity=RuleSeverity.ERROR)
    violations = rule.check_live(secdef_db, schemas=[_SCRATCH_SCHEMA])
    assert all(v.severity == RuleSeverity.ERROR for v in violations)


def test_check_live_message_references_cve(secdef_db: psycopg.Connection) -> None:
    rule = Sec002SecurityDefinerSearchPath()
    violations = rule.check_live(secdef_db, schemas=[_SCRATCH_SCHEMA])
    assert all("CVE-2018-1058" in v.message for v in violations)


def test_check_live_no_file_path_on_violations(secdef_db: psycopg.Connection) -> None:
    """Live violations have no file_path (no source attribution)."""
    rule = Sec002SecurityDefinerSearchPath()
    violations = rule.check_live(secdef_db, schemas=[_SCRATCH_SCHEMA])
    assert all(v.file_path is None for v in violations)


def test_check_live_from_current_is_pinned(clean_test_db: psycopg.Connection) -> None:
    """SET search_path FROM CURRENT populates proconfig → live path agrees with static."""
    schema = "confiture_sec002_fc_test"
    conn = clean_test_db
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            cur.execute(
                f"""
                CREATE OR REPLACE FUNCTION {schema}.f_fromcurrent()
                    RETURNS void LANGUAGE plpgsql
                    SECURITY DEFINER SET search_path FROM CURRENT
                    AS $$ BEGIN END $$
                """
            )
        conn.commit()

        rule = Sec002SecurityDefinerSearchPath()
        violations = rule.check_live(conn, schemas=[schema])
        flagged = {v.object_name for v in violations}
        assert f"{schema}.f_fromcurrent" not in flagged
    finally:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.commit()


# ---------------------------------------------------------------------------
# Cycle 3: CLI --against-db
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, security_lint_body: str = "") -> Path:
    cfg = tmp_path / "confiture.yaml"
    import os

    url = os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")
    body = textwrap.dedent(
        f"""\
        name: test
        database_url: {url}
        include_dirs: []
        """
    )
    if security_lint_body:
        body += textwrap.dedent(security_lint_body)
    cfg.write_text(body)
    return cfg


def test_against_db_flag_runs_live(secdef_db: psycopg.Connection, tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        f"""
        security_lint:
          enabled: true
          apply_to: ["{_SCRATCH_SCHEMA}"]
          severity: error
        """,
    )
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-security-definer",
            "--against-db",
            "--schemas",
            _SCRATCH_SCHEMA,
            "--config",
            str(cfg),
        ],
    )
    assert result.exit_code == 1, result.output
    assert "sec_002" in result.output


def test_against_db_clean_exits_0(clean_test_db: psycopg.Connection, tmp_path: Path) -> None:
    """When no unpinned SECURITY DEFINER functions exist, exit 0."""
    schema = "confiture_sec002_clean"
    conn = clean_test_db
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            cur.execute(
                f"""
                CREATE OR REPLACE FUNCTION {schema}.f_safe()
                    RETURNS void LANGUAGE plpgsql
                    SECURITY DEFINER SET search_path = ''
                    AS $$ BEGIN END $$
                """
            )
        conn.commit()

        cfg = _write_config(
            tmp_path,
            f"""
            security_lint:
              enabled: true
              apply_to: ["{schema}"]
              severity: error
            """,
        )
        result = CliRunner().invoke(
            app,
            [
                "migrate",
                "validate",
                "--check-security-definer",
                "--against-db",
                "--schemas",
                schema,
                "--config",
                str(cfg),
            ],
        )
        assert result.exit_code == 0, result.output
    finally:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.commit()


def test_live_error_severity_exit1(secdef_db: psycopg.Connection, tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        f"""
        security_lint:
          enabled: true
          apply_to: ["{_SCRATCH_SCHEMA}"]
          severity: error
        """,
    )
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-security-definer",
            "--against-db",
            "--schemas",
            _SCRATCH_SCHEMA,
            "--config",
            str(cfg),
        ],
    )
    assert result.exit_code == 1


def test_static_and_live_agree_from_current(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    """FROM CURRENT: both static DDL scan and live catalog report no violation."""
    schema = "confiture_sec002_agree"
    conn = clean_test_db
    sql_content = f"""
CREATE OR REPLACE FUNCTION {schema}.f_fromcurrent()
    RETURNS void LANGUAGE plpgsql
    SECURITY DEFINER SET search_path FROM CURRENT
    AS $$ BEGIN END $$;
"""
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            cur.execute(sql_content)
        conn.commit()

        # Static scan
        sql_file = tmp_path / "fn.sql"
        sql_file.write_text(sql_content)
        rule = Sec002SecurityDefinerSearchPath()
        static_violations = rule.check([sql_file])
        assert not static_violations, f"Static path false-positive: {static_violations}"

        # Live scan
        live_violations = rule.check_live(conn, schemas=[schema])
        assert not live_violations, f"Live path false-positive: {live_violations}"
    finally:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.commit()
