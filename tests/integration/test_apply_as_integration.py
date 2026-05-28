"""Integration tests for ``migrate apply-as`` (issue #137 part 2)."""

from __future__ import annotations

import textwrap
import uuid
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app


@pytest.fixture()
def apply_as_db() -> str:
    db_name = f"confiture_apply_as_{uuid.uuid4().hex[:8]}"
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
        try:
            admin = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
            admin.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            admin.close()
        except psycopg.OperationalError:
            pass


def _write_migration(migrations_dir: Path, version: str, *, requires_superuser: bool):
    migrations_dir.mkdir(parents=True, exist_ok=True)
    body = textwrap.dedent(
        f"""
        from confiture.models.migration import Migration


        class M(Migration):
            version = '{version}'
            name = 'apply_as_test'
            requires_superuser = {requires_superuser!r}

            def up(self) -> None:
                self.connection.execute('CREATE TABLE apply_as_target_{version} (id int)')

            def down(self) -> None:
                self.connection.execute('DROP TABLE apply_as_target_{version}')
        """
    )
    (migrations_dir / f"{version}_apply_as_test.py").write_text(body)


def _write_config(tmp_path: Path, db_url: str) -> Path:
    cfg = tmp_path / "confiture.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            name: apply-as-test
            database_url: {db_url}
            include_dirs: []
            apply_as:
              postgres:
                url: {db_url}
            """
        )
    )
    return cfg


@pytest.mark.integration
def test_apply_as_records_role_in_tracking_table(apply_as_db: str, tmp_path: Path) -> None:
    migrations_dir = tmp_path / "db" / "migrations"
    _write_migration(migrations_dir, "20260528150000", requires_superuser=True)
    cfg = _write_config(tmp_path, apply_as_db)

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "apply-as",
            "postgres",
            "20260528150000",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert result.exit_code == 0, result.output

    # Verify applied_by recorded as 'postgres'.
    with psycopg.connect(apply_as_db) as conn:
        row = conn.execute(
            "SELECT version, applied_by FROM tb_confiture WHERE version = %s",
            ("20260528150000",),
        ).fetchone()
        assert row is not None
        assert row[1] == "postgres"


@pytest.mark.integration
def test_apply_as_refuses_unknown_version(apply_as_db: str, tmp_path: Path) -> None:
    migrations_dir = tmp_path / "db" / "migrations"
    migrations_dir.mkdir(parents=True)
    cfg = _write_config(tmp_path, apply_as_db)

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "apply-as",
            "postgres",
            "99999999999999",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert result.exit_code == 2, result.output


@pytest.mark.integration
def test_apply_as_refuses_already_applied(apply_as_db: str, tmp_path: Path) -> None:
    migrations_dir = tmp_path / "db" / "migrations"
    _write_migration(migrations_dir, "20260528150100", requires_superuser=True)
    cfg = _write_config(tmp_path, apply_as_db)

    runner = CliRunner()
    first = runner.invoke(
        app,
        [
            "migrate",
            "apply-as",
            "postgres",
            "20260528150100",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert first.exit_code == 0, first.output

    second = runner.invoke(
        app,
        [
            "migrate",
            "apply-as",
            "postgres",
            "20260528150100",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert second.exit_code == 2, second.output


@pytest.mark.integration
def test_legacy_rows_retain_null_applied_by(apply_as_db: str) -> None:
    """``applied_by IS NULL`` for rows added before the column existed (invariant)."""
    # Simulate a pre-0.17.0 install: manually create tb_confiture
    # without the applied_by column and insert one row.
    with psycopg.connect(apply_as_db, autocommit=True) as conn:
        conn.execute(
            """
            CREATE TABLE tb_confiture (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                pk_confiture BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
                slug TEXT NOT NULL UNIQUE,
                version VARCHAR(255) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                execution_time_ms INTEGER,
                checksum VARCHAR(64)
            )
            """
        )
        conn.execute(
            "INSERT INTO tb_confiture (slug, version, name, execution_time_ms) "
            "VALUES ('legacy_slug', '20260101000000', 'legacy', 100)"
        )

    # Initializing the migrator now should add the applied_by column
    # via ALTER TABLE … ADD COLUMN IF NOT EXISTS, and the legacy row
    # should keep applied_by IS NULL.
    from confiture.core._migrator.engine import Migrator

    with psycopg.connect(apply_as_db) as conn:
        migrator = Migrator(connection=conn, migration_table="tb_confiture")
        migrator.initialize()
        row = conn.execute(
            "SELECT version, applied_by FROM tb_confiture WHERE version = '20260101000000'"
        ).fetchone()
        assert row is not None
        assert row[1] is None  # legacy row → applied_by IS NULL invariant
