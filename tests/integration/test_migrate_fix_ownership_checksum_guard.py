"""Integration tests for the checksum-drift guard on ``migrate fix --ownership``.

The guard refuses to rewrite migration files whose version is already
recorded in the local tracking table, unless ``--force`` is also set.
This protects users from silently breaking ``migrate verify``.
"""

from __future__ import annotations

import os
import textwrap
from collections.abc import Generator
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

pytest.importorskip("pglast")


@pytest.fixture
def pg_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


@pytest.fixture
def tracking_db(pg_url: str) -> Generator[psycopg.Connection, None, None]:
    """Provide a connection with a clean tracking table."""
    try:
        conn = psycopg.connect(pg_url, autocommit=False)
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")

    def _cleanup() -> None:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS public.tb_confiture CASCADE")
        conn.commit()

    _cleanup()
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE public.tb_confiture ("
            "  version text PRIMARY KEY, "
            "  name text NOT NULL, "
            "  applied_at timestamptz NOT NULL DEFAULT now(), "
            "  checksum text"
            ")"
        )
    conn.commit()

    yield conn

    _cleanup()
    conn.close()


def _write_config(tmp_path: Path, pg_url: str) -> Path:
    cfg = tmp_path / "confiture.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            name: test
            database_url: {pg_url}
            include_dirs: []
            migration:
              tracking_table: public.tb_confiture
            ownership:
              expected_owner: migrator
              apply_to:
                - schema: public
                  relkinds: [r]
            """
        )
    )
    return cfg


def _write_migration(tmp_path: Path, name: str, sql: str) -> Path:
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True, exist_ok=True)
    p = migrations / name
    p.write_text(sql)
    return p


def test_refuses_to_rewrite_already_applied_migration(
    tmp_path: Path, tracking_db: psycopg.Connection, pg_url: str
) -> None:
    cfg = _write_config(tmp_path, pg_url)
    path = _write_migration(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )
    original = path.read_text()

    # Record the migration as applied.
    with tracking_db.cursor() as cur:
        cur.execute(
            "INSERT INTO public.tb_confiture (version, name) VALUES (%s, %s)",
            ("20260527090000", "add_foo"),
        )
    tracking_db.commit()

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "fix",
            "--ownership",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
        ],
    )
    assert result.exit_code == 2, result.output
    assert "Refused" in result.output
    assert path.read_text() == original  # unchanged


def test_force_overrides_checksum_guard(
    tmp_path: Path, tracking_db: psycopg.Connection, pg_url: str
) -> None:
    cfg = _write_config(tmp_path, pg_url)
    path = _write_migration(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )

    with tracking_db.cursor() as cur:
        cur.execute(
            "INSERT INTO public.tb_confiture (version, name) VALUES (%s, %s)",
            ("20260527090000", "add_foo"),
        )
    tracking_db.commit()

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "fix",
            "--ownership",
            "--force",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "ALTER TABLE public.foo OWNER TO migrator;" in path.read_text()


def test_unapplied_migration_rewritten_without_force(
    tmp_path: Path, tracking_db: psycopg.Connection, pg_url: str
) -> None:
    """Greenfield (no rows in tracking) rewrites cleanly without --force."""
    cfg = _write_config(tmp_path, pg_url)
    path = _write_migration(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )

    # Tracking table exists but empty.
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "fix",
            "--ownership",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "ALTER TABLE public.foo OWNER TO migrator;" in path.read_text()


def test_dry_run_warns_without_exit_nonzero(
    tmp_path: Path, tracking_db: psycopg.Connection, pg_url: str
) -> None:
    """``--dry-run`` surfaces the would-be-refused files but still exits 0."""
    cfg = _write_config(tmp_path, pg_url)
    path = _write_migration(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )
    original = path.read_text()

    with tracking_db.cursor() as cur:
        cur.execute(
            "INSERT INTO public.tb_confiture (version, name) VALUES (%s, %s)",
            ("20260527090000", "add_foo"),
        )
    tracking_db.commit()

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "fix",
            "--ownership",
            "--dry-run",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
        ],
    )
    # Dry-run never exits non-zero on the guard alone — the guard only
    # applies to the apply path; dry-run is read-only.
    assert result.exit_code == 0, result.output
    assert path.read_text() == original
