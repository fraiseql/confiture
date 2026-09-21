"""``confiture migrate fix-signatures``, run by its command line against a real database.

The routine goldens (``test_routine_goldens.py``) record what the command *plans*.
Nothing ran ``--mode apply``, which executes ``DROP FUNCTION`` and the source's
``CREATE`` in one transaction — so these tests do, and read the catalogue after.

The stale overloads here are the shape a deploy leaves behind: a migration wrote
``CREATE OR REPLACE FUNCTION f(bigint)`` over an ``f(integer)``, which PostgreSQL
treats as a second function rather than a replacement.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.error_codes import exit_code_of

_CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "routine_drift"

pytestmark = pytest.mark.integration

runner = CliRunner()

_CONFIG = "db/environments/test.yaml"

_TOTAL = (
    "CREATE OR REPLACE FUNCTION app.total(p_a bigint) RETURNS bigint\n"
    "LANGUAGE sql AS $$ SELECT p_a * 2 $$;\n"
)


@pytest.fixture
def db(fresh_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA app")
        yield conn


@pytest.fixture
def project(tmp_path: Path, fresh_database: str) -> Iterator[Path]:
    """A project whose schema lives in ``db/schema/20_app.sql`` — written per test."""
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir()
    (tmp_path / _CONFIG).write_text(
        yaml.safe_dump(
            {"name": "test", "database_url": fresh_database, "include_dirs": ["db/schema"]}
        )
    )
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _source(project: Path, sql: str) -> None:
    (project / "db" / "schema" / "20_app.sql").write_text("CREATE SCHEMA app;\n\n" + sql)


def _overloads(conn: psycopg.Connection, name: str) -> list[str]:
    rows = conn.execute(
        "SELECT p.oid::regprocedure::text FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'app' AND p.proname = %s ORDER BY 1",
        (name,),
    )
    return [row[0] for row in rows]


def _fix(*extra: str) -> tuple[int, dict, str]:
    result = runner.invoke(
        app, ["migrate", "fix-signatures", "-c", _CONFIG, "--format", "json", *extra]
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {}
    return result.exit_code, payload, result.output


def test_apply_drops_the_stale_overload_and_keeps_the_source(
    project: Path, db: psycopg.Connection
) -> None:
    _source(project, _TOTAL)
    db.execute(
        "CREATE FUNCTION app.total(p_a integer) RETURNS integer LANGUAGE sql AS $$ SELECT p_a * 3 $$"
    )

    code, payload, output = _fix("--mode", "apply")

    assert code == 0, output
    assert (payload["status"], payload["remaining_drift"]) == ("applied", False)
    assert _overloads(db, "total") == ["app.total(bigint)"]
    assert db.execute("SELECT app.total(21)").fetchone() == (42,)


def test_plan_is_the_default_and_changes_nothing(project: Path, db: psycopg.Connection) -> None:
    _source(project, _TOTAL)
    db.execute(
        "CREATE FUNCTION app.total(p_a integer) RETURNS integer LANGUAGE sql AS $$ SELECT p_a $$"
    )

    code, payload, output = _fix()

    assert code == 0, output
    assert (payload["status"], payload["fixes_planned"]) == ("dry_run", 1)
    assert _overloads(db, "total") == ["app.total(integer)"]


def test_apply_leaves_the_current_overload_a_plain_create_declares(
    project: Path, db: psycopg.Connection
) -> None:
    """The deploy shape: both overloads live, the source written ``CREATE FUNCTION``."""
    _source(project, _TOTAL.replace("CREATE OR REPLACE", "CREATE"))
    db.execute(
        "CREATE FUNCTION app.total(p_a integer) RETURNS integer LANGUAGE sql AS $$ SELECT p_a $$"
    )
    db.execute(
        "CREATE FUNCTION app.total(p_a bigint) RETURNS bigint LANGUAGE sql AS $$ SELECT p_a * 2 $$"
    )

    code, payload, output = _fix("--mode", "apply")

    assert code == 0, output
    assert payload["status"] == "applied"
    assert _overloads(db, "total") == ["app.total(bigint)"]


def test_check_body_replaces_a_drifted_body(project: Path, db: psycopg.Connection) -> None:
    _source(project, _TOTAL)
    db.execute(
        "CREATE FUNCTION app.total(p_a bigint) RETURNS bigint LANGUAGE sql AS $$ SELECT p_a * 3 $$"
    )

    code, payload, output = _fix("--check-body", "--mode", "apply")

    assert code == 0, output
    assert (payload["body_drift_fixes_applied"], payload["remaining_body_drift"]) == (1, False)
    assert db.execute("SELECT app.total(21)").fetchone() == (42,)


def test_check_body_replaces_a_body_a_plain_create_declares(
    project: Path, db: psycopg.Connection
) -> None:
    """The routine goldens' shape: re-running ``CREATE FUNCTION`` as written would fail."""
    _source(project, _TOTAL.replace("CREATE OR REPLACE", "CREATE"))
    db.execute(
        "CREATE FUNCTION app.total(p_a bigint) RETURNS bigint LANGUAGE sql AS $$ SELECT p_a * 3 $$"
    )

    code, payload, output = _fix("--check-body", "--mode", "apply")

    assert code == 0, output
    assert payload["remaining_body_drift"] is False
    assert db.execute("SELECT app.total(21)").fetchone() == (42,)


def test_apply_drops_a_stale_procedure(project: Path, db: psycopg.Connection) -> None:
    _source(
        project,
        "CREATE OR REPLACE PROCEDURE app.touch(p_a bigint)\nLANGUAGE sql AS $$ SELECT p_a $$;\n",
    )
    db.execute("CREATE PROCEDURE app.touch(p_a integer) LANGUAGE sql AS $$ SELECT p_a $$")

    code, payload, output = _fix("--mode", "apply")

    assert code == 0, output
    assert payload["status"] == "applied"
    assert _overloads(db, "touch") == ["app.touch(bigint)"]


def test_a_fix_that_fails_rolls_every_fix_back(project: Path, db: psycopg.Connection) -> None:
    _source(
        project,
        _TOTAL + "\nCREATE OR REPLACE FUNCTION app.label(p_a bigint) RETURNS text\n"
        "LANGUAGE sql AS $$ SELECT p_a::text $$;\n",
    )
    db.execute(
        "CREATE FUNCTION app.total(p_a integer) RETURNS integer LANGUAGE sql AS $$ SELECT p_a $$"
    )
    db.execute(
        "CREATE FUNCTION app.label(p_a integer) RETURNS text LANGUAGE sql AS $$ SELECT '' $$"
    )
    db.execute("CREATE VIEW app.v AS SELECT app.label(1) AS l")

    code, _payload, output = _fix("--mode", "apply")

    assert code == exit_code_of("SQL_001"), output
    assert "depend on it" in output, output
    assert _overloads(db, "total") == ["app.total(integer)"]
    assert _overloads(db, "label") == ["app.label(integer)"]


def test_the_plan_the_goldens_record_applies_and_leaves_no_drift(
    tmp_path: Path, fresh_database: str
) -> None:
    """The routine goldens' drift scenario, fixed: the second run finds nothing."""
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute((_CORPUS / "schema.sql").read_text())
        conn.execute((_CORPUS / "live_changes.sql").read_text())
    config = tmp_path / "confiture.yaml"
    config.write_text(f"name: golden\ndatabase_url: {fresh_database}\ninclude_dirs: []\n")
    argv = [
        "migrate",
        "fix-signatures",
        "--check-body",
        "-c",
        str(config),
        "--schema",
        str(_CORPUS / "schema.sql"),
        "--format",
        "json",
    ]

    applied = runner.invoke(app, [*argv, "--mode", "apply"])
    assert applied.exit_code == 0, applied.output
    again = runner.invoke(app, argv)

    assert again.exit_code == 0, again.output
    assert json.loads(again.stdout)["status"] == "clean"
