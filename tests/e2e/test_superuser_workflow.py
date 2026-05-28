"""End-to-end test for the halt → apply-as → resume workflow (issue #137)."""

from __future__ import annotations

import textwrap
import uuid
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app


@pytest.fixture()
def workflow_db() -> str:
    db_name = f"confiture_su_workflow_{uuid.uuid4().hex[:8]}"
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


def _write_chain(migrations_dir: Path) -> None:
    """Three migrations: 001, 002 (requires_superuser), 003."""
    migrations_dir.mkdir(parents=True, exist_ok=True)
    (migrations_dir / "20260528160001_first.py").write_text(
        textwrap.dedent(
            """
            from confiture.models.migration import Migration

            class M(Migration):
                version = '20260528160001'
                name = 'first'
                def up(self):
                    self.connection.execute('CREATE TABLE workflow_a (id int)')
                def down(self):
                    self.connection.execute('DROP TABLE workflow_a')
            """
        )
    )
    (migrations_dir / "20260528160002_second.py").write_text(
        textwrap.dedent(
            """
            from confiture.models.migration import Migration

            class M(Migration):
                version = '20260528160002'
                name = 'second'
                requires_superuser = True
                def up(self):
                    self.connection.execute('CREATE TABLE workflow_b (id int)')
                def down(self):
                    self.connection.execute('DROP TABLE workflow_b')
            """
        )
    )
    (migrations_dir / "20260528160003_third.py").write_text(
        textwrap.dedent(
            """
            from confiture.models.migration import Migration

            class M(Migration):
                version = '20260528160003'
                name = 'third'
                def up(self):
                    self.connection.execute('CREATE TABLE workflow_c (id int)')
                def down(self):
                    self.connection.execute('DROP TABLE workflow_c')
            """
        )
    )


def _write_config(tmp_path: Path, db_url: str) -> Path:
    cfg = tmp_path / "confiture.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            name: workflow-test
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
def test_halt_apply_as_resume_workflow(workflow_db: str, tmp_path: Path) -> None:
    """The full workflow: up halts at #2, apply-as runs #2, up resumes at #3."""
    migrations_dir = tmp_path / "db" / "migrations"
    _write_chain(migrations_dir)
    cfg = _write_config(tmp_path, workflow_db)
    runner = CliRunner()

    # Step 1: `migrate up` applies #1, halts at #2 (exit 1).
    up1 = runner.invoke(
        app,
        [
            "migrate",
            "up",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert up1.exit_code == 1, up1.output

    # #1 applied, #2/#3 not applied yet.
    with psycopg.connect(workflow_db) as conn:
        applied = {
            row[0]
            for row in conn.execute("SELECT version FROM tb_confiture ORDER BY version").fetchall()
        }
        assert applied == {"20260528160001"}

    # Step 2: `migrate apply-as postgres 20260528160002`.
    apply_as = runner.invoke(
        app,
        [
            "migrate",
            "apply-as",
            "postgres",
            "20260528160002",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert apply_as.exit_code == 0, apply_as.output

    with psycopg.connect(workflow_db) as conn:
        row = conn.execute(
            "SELECT applied_by FROM tb_confiture WHERE version = '20260528160002'"
        ).fetchone()
        assert row is not None
        assert row[0] == "postgres"

    # Step 3: `migrate up` resumes at #3.
    up2 = runner.invoke(
        app,
        [
            "migrate",
            "up",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert up2.exit_code == 0, up2.output

    with psycopg.connect(workflow_db) as conn:
        applied = {
            row[0]
            for row in conn.execute("SELECT version FROM tb_confiture ORDER BY version").fetchall()
        }
        assert applied == {
            "20260528160001",
            "20260528160002",
            "20260528160003",
        }
