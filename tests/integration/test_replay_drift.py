"""DB-backed tests for replay-based function-body drift (#179).

The clean production drift signal: rebuild the expected database by replaying
base + all migrations into a scratch DB (no hot-patches), then diff function
bodies against live. ``live − replayed`` is exactly the definitions that no
migration produced — true out-of-band hot-patches.

The contrast with ``--check-body`` (which builds the expected side from source
DDL) is the whole point: a body that changed in the DDL but never got a migration
is *backlog*, and would swamp ``--check-body``; replay excludes it because it
never consults the source DDL.

Requires a PostgreSQL server at ``CONFITURE_TEST_DB_URL``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from pathlib import Path

import psycopg
import pytest

from confiture.core._migrator.session import MigratorSession
from confiture.core.validation.replay_drift import check_replay_drift
from confiture.exceptions import SchemaError


def _server_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


def _maint(url: str) -> str:
    # postgresql:///confiture_test → postgresql:///postgres, host form preserved.
    return url.rsplit("/", 1)[0] + "/postgres"


@pytest.fixture
def live_db() -> Generator[str, None, None]:
    """A fresh, persistent live database (dropped after the test)."""
    server = _server_url()
    maint = _maint(server)
    name = f"confiture_replay_live_{uuid.uuid4().hex[:8]}"
    try:
        conn = psycopg.connect(maint, autocommit=True)
    except psycopg.OperationalError as exc:  # pragma: no cover - env dependent
        pytest.skip(f"PostgreSQL not available: {exc}")
    conn.execute(f'CREATE DATABASE "{name}"')
    conn.close()

    live_url = server.rsplit("/", 1)[0] + f"/{name}"
    yield live_url

    conn = psycopg.connect(maint, autocommit=True)
    conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    conn.close()


# Two migrations: create a table + a function, then a second function.
_MIG_1 = (
    "CREATE TABLE widgets (id bigint, price numeric);\n"
    "CREATE FUNCTION public.total() RETURNS numeric\n"
    "LANGUAGE sql AS $$ SELECT coalesce(sum(price), 0) FROM widgets $$;\n"
)
_MIG_1_DOWN = "DROP FUNCTION public.total();\nDROP TABLE widgets;\n"


def _write_migrations(migrations_dir: Path) -> None:
    migrations_dir.mkdir(parents=True, exist_ok=True)
    (migrations_dir / "20260708000001_init.up.sql").write_text(_MIG_1)
    (migrations_dir / "20260708000001_init.down.sql").write_text(_MIG_1_DOWN)


def _config(tmp_path: Path, live_url: str) -> Path:
    config = tmp_path / "confiture.yaml"
    config.write_text(f"name: replaytest\ndatabase_url: {live_url}\ninclude_dirs:\n  - db/schema\n")
    return config


def _replay_into(live_url: str, migrations_dir: Path) -> None:
    with MigratorSession(
        config=None, migrations_dir=migrations_dir, database_url_override=live_url
    ) as session:
        result = session.up()
    assert result.success, f"live replay failed: {result.errors}"


@pytest.mark.integration
def test_hotpatch_reported(live_db: str, tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    _write_migrations(migrations_dir)
    _replay_into(live_db, migrations_dir)

    # Hot-patch a function directly on live — no migration carries this change.
    with psycopg.connect(live_db, autocommit=True) as conn:
        conn.execute(
            "CREATE OR REPLACE FUNCTION public.total() RETURNS numeric "
            "LANGUAGE sql AS $$ SELECT coalesce(sum(price), 0) * 1.2 FROM widgets $$;"
        )

    result = check_replay_drift(
        config_path=_config(tmp_path, live_db),
        migrations_dir=migrations_dir,
        schemas="public",
        ssh_via=None,
    )

    assert result.has_drift
    keys = {d.signature_key for d in result.body_report.body_drifts}
    assert keys == {"public.total()"}, f"expected only the hot-patched fn, got {keys}"


@pytest.mark.integration
def test_backlog_not_reported(live_db: str, tmp_path: Path) -> None:
    """Live built purely from migrations (no hot-patch) → no drift.

    Replay reproduces exactly what the migrations produced, so a body that only
    ever lived in source DDL (never migrated) can never appear here.
    """
    migrations_dir = tmp_path / "migrations"
    _write_migrations(migrations_dir)
    _replay_into(live_db, migrations_dir)

    result = check_replay_drift(
        config_path=_config(tmp_path, live_db),
        migrations_dir=migrations_dir,
        schemas="public",
        ssh_via=None,
    )

    assert not result.has_drift, (
        "a clean migration replay must match live; "
        f"drifts={[d.signature_key for d in result.body_report.body_drifts]}"
    )


@pytest.mark.integration
def test_broken_migration_is_error_not_false_drift(live_db: str, tmp_path: Path) -> None:
    """A migration that fails at HEAD surfaces as an error, not as drift."""
    migrations_dir = tmp_path / "migrations"
    _write_migrations(migrations_dir)
    _replay_into(live_db, migrations_dir)

    # A later migration that is broken (references a non-existent table).
    (migrations_dir / "20260708000002_broken.up.sql").write_text(
        "ALTER TABLE does_not_exist ADD COLUMN x int;\n"
    )
    (migrations_dir / "20260708000002_broken.down.sql").write_text("SELECT 1;\n")

    with pytest.raises(SchemaError, match="[Mm]igration replay"):
        check_replay_drift(
            config_path=_config(tmp_path, live_db),
            migrations_dir=migrations_dir,
            schemas="public",
            ssh_via=None,
        )
