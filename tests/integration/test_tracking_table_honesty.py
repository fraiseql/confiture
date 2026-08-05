"""No command may name a tracking table it did not resolve (issue #190).

``tracking_table`` has been configurable since v0.6.1, and ``_get_tracking_table``
resolves it correctly in most places. A handful of sites still print — or
*query* — the literal ``tb_confiture``. 0.37.0 made the inconsistency worse
rather than better: its new messages interpolate the configured name correctly,
so an operator with ``tracking_table: audit.tb_migrations`` sees both spellings
in a single session.

This module is the regression net for the whole class. It runs the commands
against a database whose ledger is deliberately **not** the default and asserts
the literal never reaches the operator. That is what catches a site nobody
enumerated — the enumerated ones each have their own unit test.

Two things this net has to get right, because getting them wrong reports a
false green:

* **The commands need a real project.** Typer resolves ``db/migrations``
  relative to the cwd, and every command exits early with "No migrations
  directory found" without one — before reaching any of the lines under test.
* **Several messages only fire on the absent-ledger path**, and the ``reinit``
  prompt is gated on ``not yes and not dry_run``. A net that always passes
  ``--yes`` never executes the destructive command's prompt at all.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

# Deliberately unlike the default in both schema and base name, so a partial
# fix (right schema, defaulted base name) still fails.
_SCHEMA = "audit"
_TABLE = "tb_migrations"
_QUALIFIED = f"{_SCHEMA}.{_TABLE}"
_ABSENT = f"{_SCHEMA}.tb_absent_ledger"

_LITERAL = "tb_confiture"

_MIGRATION_VERSION = "20260101000000"
_MIGRATION_NAME = f"{_MIGRATION_VERSION}_create_widgets"

runner = CliRunner()


@pytest.fixture
def ledger_db(test_db_url: str) -> Iterator[psycopg.Connection]:
    """A database whose migration ledger is ``audit.tb_migrations``."""
    try:
        conn = psycopg.connect(test_db_url, autocommit=True)
    except psycopg.OperationalError as exc:  # pragma: no cover - env dependent
        pytest.skip(f"PostgreSQL not available: {exc}")

    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {_SCHEMA}")
        # A stray default-named ledger must NOT exist: if it did, a command
        # that queries the literal would succeed by accident and the net would
        # pass while the bug is live.
        cur.execute(f"DROP TABLE IF EXISTS public.{_LITERAL}")
        cur.execute(f"""
            CREATE TABLE {_QUALIFIED} (
                id SERIAL PRIMARY KEY,
                version TEXT NOT NULL,
                name TEXT,
                checksum TEXT,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                execution_time_ms INTEGER
            )
        """)
        cur.execute(
            f"INSERT INTO {_QUALIFIED} (version, name, checksum) VALUES (%s, %s, %s)",
            (_MIGRATION_VERSION, "create_widgets", "sha256:deadbeef"),
        )
    try:
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
        conn.close()


@pytest.fixture
def project(tmp_path: Path, test_db_url: str) -> Iterator[Path]:
    """A minimal confiture project, with the cwd moved into it."""
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / f"{_MIGRATION_NAME}.up.sql").write_text(
        "CREATE TABLE IF NOT EXISTS widgets (id SERIAL PRIMARY KEY);\n"
    )
    (migrations / f"{_MIGRATION_NAME}.down.sql").write_text("DROP TABLE IF EXISTS widgets;\n")
    (tmp_path / "db" / "schema").mkdir(parents=True, exist_ok=True)

    for label, table in (("present", _QUALIFIED), ("absent", _ABSENT)):
        (tmp_path / f"env-{label}.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "test",
                    "database_url": test_db_url,
                    "include_dirs": ["db/schema"],
                    "migration": {"tracking_table": table},
                }
            )
        )

    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _cfg(project: Path, which: str = "present") -> str:
    return str(project / f"env-{which}.yaml")


def _assert_no_literal(result, command: str) -> None:
    """The default table name must appear nowhere in operator-facing output."""
    assert _LITERAL not in result.output, (
        f"`{command}` surfaced the literal {_LITERAL!r} to an operator whose "
        f"configured tracking table is not the default. Resolve the name via "
        f"_get_tracking_table(config_data) instead of hardcoding it.\n"
        f"--- output ---\n{result.output}"
    )


@pytest.mark.integration
def test_migrate_status_names_the_configured_table(ledger_db, project: Path) -> None:
    result = runner.invoke(app, ["migrate", "status", "--config", _cfg(project)])
    _assert_no_literal(result, "migrate status")


@pytest.mark.integration
def test_migrate_status_absent_ledger_names_the_configured_table(ledger_db, project: Path) -> None:
    """The `tracking_table_absent` warning — text mode (`migrate_core.py:369`)."""
    result = runner.invoke(app, ["migrate", "status", "--config", _cfg(project, "absent")])
    _assert_no_literal(result, "migrate status (ledger absent)")


@pytest.mark.integration
def test_migrate_status_absent_ledger_json_names_the_configured_table(
    ledger_db, project: Path
) -> None:
    """The same warning on the JSON path (`migrate_core.py:302`).

    Separate from the text case because the two messages are independent string
    literals — fixing one and not the other is the exact shape of this bug.
    """
    result = runner.invoke(
        app,
        ["migrate", "status", "--config", _cfg(project, "absent"), "--format", "json"],
    )
    _assert_no_literal(result, "migrate status --format json (ledger absent)")


@pytest.mark.integration
def test_migrate_introspect_names_the_configured_table(ledger_db, project: Path) -> None:
    result = runner.invoke(app, ["migrate", "introspect", "--config", _cfg(project)])
    _assert_no_literal(result, "migrate introspect")


@pytest.mark.integration
def test_verify_checksums_names_the_configured_table(ledger_db, project: Path) -> None:
    result = runner.invoke(app, ["verify-checksums", "--config", _cfg(project)])
    _assert_no_literal(result, "verify-checksums")


@pytest.mark.integration
def test_migrate_reinit_confirmation_prompt_names_the_configured_table(
    ledger_db, project: Path
) -> None:
    """The destructive one — its confirmation prompt must not name the wrong table.

    Note the invocation: **not** ``--yes`` and **not** ``--dry-run``. The prompt
    is gated on ``if not yes and not dry_run``, so either flag skips the very
    line under test. Answering ``n`` aborts before anything is deleted.
    """
    result = runner.invoke(app, ["migrate", "reinit", "--config", _cfg(project)], input="n\n")
    _assert_no_literal(result, "migrate reinit (confirmation prompt)")
