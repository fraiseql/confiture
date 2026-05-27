"""#131: --dry-run-execute must roll back all migration changes, not commit them."""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import Generator

import psycopg
import pytest

from confiture.core._migrator.session import MigratorSession


@pytest.fixture()
def dry_run_db() -> Generator[str, None, None]:
    """Throwaway DB for one test."""
    db_name = f"confiture_dry_run_test_{uuid.uuid4().hex[:8]}"
    use_subprocess = False
    try:
        subprocess.run(["createdb", db_name], check=True, capture_output=True)
        use_subprocess = True
    except (FileNotFoundError, subprocess.CalledProcessError):
        try:
            conn = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
            conn.execute(f'CREATE DATABASE "{db_name}"')
            conn.close()
        except psycopg.OperationalError as e:
            pytest.skip(f"PostgreSQL not available: {e}")

    yield f"postgresql://localhost/{db_name}"

    if use_subprocess:
        subprocess.run(["dropdb", db_name], capture_output=True)
    else:
        try:
            conn = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
            conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            conn.close()
        except psycopg.OperationalError:
            pass


@pytest.mark.integration
def test_dry_run_execute_does_not_persist_a_single_successful_migration(
    dry_run_db: str, tmp_path
) -> None:
    """One migration, success path: must roll back."""
    (tmp_path / "20260527000001_create_widgets.up.sql").write_text(
        "CREATE TABLE widgets (id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL);\n"
    )
    (tmp_path / "20260527000001_create_widgets.down.sql").write_text("DROP TABLE widgets;\n")

    session = MigratorSession(
        config=None, migrations_dir=tmp_path, database_url_override=dry_run_db
    )
    with session:
        result = session.up(dry_run_execute=True)

    assert result.success is True, f"errors: {result.errors}"
    assert result.dry_run_execute is True

    conn = psycopg.connect(dry_run_db)
    try:
        row = conn.execute("SELECT to_regclass('public.widgets')").fetchone()
        assert row[0] is None, "widgets table must not persist after --dry-run-execute"
    finally:
        conn.close()


@pytest.mark.integration
def test_dry_run_execute_does_not_persist_multiple_successful_migrations(
    dry_run_db: str, tmp_path
) -> None:
    """Two migrations, both success: outer SAVEPOINT survives the second migration's
    apply() too. Pins the regression to ensure the per-migration commit is suppressed
    for every migration in the run, not just the last one."""
    (tmp_path / "20260527000001_create_a.up.sql").write_text(
        "CREATE TABLE alpha (id BIGSERIAL PRIMARY KEY);\n"
    )
    (tmp_path / "20260527000001_create_a.down.sql").write_text("DROP TABLE alpha;\n")
    (tmp_path / "20260527000002_create_b.up.sql").write_text(
        "CREATE TABLE beta (id BIGSERIAL PRIMARY KEY);\n"
    )
    (tmp_path / "20260527000002_create_b.down.sql").write_text("DROP TABLE beta;\n")

    session = MigratorSession(
        config=None, migrations_dir=tmp_path, database_url_override=dry_run_db
    )
    with session:
        result = session.up(dry_run_execute=True)

    assert result.success is True, f"errors: {result.errors}"

    conn = psycopg.connect(dry_run_db)
    try:
        for table in ("alpha", "beta"):
            row = conn.execute(f"SELECT to_regclass('public.{table}')").fetchone()
            assert row[0] is None, f"{table} table must not persist"
    finally:
        conn.close()


@pytest.mark.integration
def test_dry_run_execute_tracking_table_not_populated(dry_run_db: str, tmp_path) -> None:
    """A successful dry-run-execute must NOT leave rows in tb_confiture either —
    those inserts happen inside _apply_transactional and must also roll back."""
    (tmp_path / "20260527000001_create_widgets.up.sql").write_text(
        "CREATE TABLE widgets (id BIGSERIAL PRIMARY KEY);\n"
    )
    (tmp_path / "20260527000001_create_widgets.down.sql").write_text("DROP TABLE widgets;\n")

    session = MigratorSession(
        config=None, migrations_dir=tmp_path, database_url_override=dry_run_db
    )
    with session:
        result = session.up(dry_run_execute=True)

    assert result.success is True, f"errors: {result.errors}"

    conn = psycopg.connect(dry_run_db)
    try:
        # tb_confiture may not even exist (initialize() also rolls back) — that's fine.
        row = conn.execute("SELECT to_regclass('public.tb_confiture')").fetchone()
        if row[0] is not None:
            cnt = conn.execute("SELECT COUNT(*) FROM tb_confiture").fetchone()[0]
            assert cnt == 0, "tracking table must have no rows after dry-run-execute"
    finally:
        conn.close()


@pytest.mark.integration
def test_dry_run_execute_rolls_back_when_a_later_migration_fails(dry_run_db: str, tmp_path) -> None:
    """Two migrations, second one fails: NEITHER persists."""
    (tmp_path / "20260527000001_create_a.up.sql").write_text(
        "CREATE TABLE alpha (id BIGSERIAL PRIMARY KEY);\n"
    )
    (tmp_path / "20260527000001_create_a.down.sql").write_text("DROP TABLE alpha;\n")
    (tmp_path / "20260527000002_broken.up.sql").write_text("THIS IS NOT VALID SQL;\n")
    (tmp_path / "20260527000002_broken.down.sql").write_text("SELECT 1;\n")

    session = MigratorSession(
        config=None, migrations_dir=tmp_path, database_url_override=dry_run_db
    )
    with session:
        result = session.up(dry_run_execute=True)

    assert result.success is False  # the second migration failed
    conn = psycopg.connect(dry_run_db)
    try:
        row = conn.execute("SELECT to_regclass('public.alpha')").fetchone()
        assert row[0] is None, "first migration must also have rolled back"
    finally:
        conn.close()
