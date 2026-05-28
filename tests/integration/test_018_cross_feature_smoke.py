"""Cross-feature smoke test for 0.18.0 (issues #126, #136, #137).

Exercises the bundled features end-to-end:

  #137 bootstrap — `confiture bootstrap --apply` provisions an env from scratch.
  #137 superuser — `migrate up` halts on a `requires_superuser=True` migration;
                   `migrate apply-as postgres <version>` resolves; `migrate up`
                   resumes.
  #136 func_001 — `migrate validate --check-function-uniqueness` flags a
                  duplicate `CREATE FUNCTION`.
  #137 own_002 — `migrate validate --check-ownership-coverage` flags a
                 bare ALTER OWNER on a pre-existing object.

Requires PostgreSQL on localhost as the `postgres` superuser.
"""

from __future__ import annotations

import textwrap
import uuid
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

# pglast is required by the validate checks; skip the whole suite
# without it (it's an [ast] extra in pyproject).
pytest.importorskip("pglast")


def _provision_db() -> str:
    db_name = f"confiture_018_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
        admin.execute(f'CREATE DATABASE "{db_name}"')
        admin.close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
    return f"postgresql://localhost/{db_name}"


def _drop_db(db_url: str) -> None:
    db_name = db_url.rsplit("/", 1)[-1]
    try:
        admin = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
        admin.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        admin.close()
    except psycopg.OperationalError:
        pass


def _drop_role(role: str) -> None:
    try:
        admin = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
    except psycopg.OperationalError:
        return
    try:
        try:
            admin.execute(f"DROP OWNED BY {role} CASCADE")
        except psycopg.Error:
            pass
        try:
            admin.execute(f'DROP ROLE IF EXISTS "{role}"')
        except psycopg.Error:
            pass
    finally:
        admin.close()


@pytest.fixture()
def smoke_env() -> tuple[str, str]:
    """Throwaway DB plus a dedicated migrator role name."""
    role = "smoke_018_migrator"
    _drop_role(role)
    db_url = _provision_db()
    try:
        yield db_url, role
    finally:
        _drop_role(role)
        _drop_db(db_url)


def _write_config(tmp_path: Path, db_url: str, role: str) -> Path:
    cfg = tmp_path / "confiture.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            name: smoke-018
            database_url: {db_url}
            include_dirs: []
            ownership:
              expected_owner: {role}
              apply_to:
                - schema: public
              bootstrap_connection_url: {db_url}
            apply_as:
              postgres:
                url: {db_url}
            function_coverage:
              enabled: true
              apply_to: ["*"]
            """
        )
    )
    return cfg


@pytest.mark.integration
def test_bootstrap_apply_then_migrate_with_superuser_halt_and_apply_as(
    smoke_env: tuple[str, str], tmp_path: Path
) -> None:
    db_url, role = smoke_env
    cfg = _write_config(tmp_path, db_url, role)
    migrations_dir = tmp_path / "db" / "migrations"
    migrations_dir.mkdir(parents=True)

    # Two-migration chain: routine #1 then requires_superuser=True #2.
    (migrations_dir / "20260528180001_first.py").write_text(
        textwrap.dedent(
            """
            from confiture.models.migration import Migration

            class M(Migration):
                version = '20260528180001'
                name = 'first'
                def up(self):
                    self.connection.execute('CREATE TABLE smoke_a (id int)')
                def down(self):
                    self.connection.execute('DROP TABLE smoke_a')
            """
        )
    )
    (migrations_dir / "20260528180002_second.py").write_text(
        textwrap.dedent(
            """
            from confiture.models.migration import Migration

            class M(Migration):
                version = '20260528180002'
                name = 'second'
                requires_superuser = True
                def up(self):
                    self.connection.execute('CREATE TABLE smoke_b (id int)')
                def down(self):
                    self.connection.execute('DROP TABLE smoke_b')
            """
        )
    )

    runner = CliRunner()

    # #137 — bootstrap --apply provisions the migrator role.
    boot = runner.invoke(
        app,
        ["bootstrap", "--apply", "--all-schemas", "--config", str(cfg)],
    )
    assert boot.exit_code == 0, boot.output

    with psycopg.connect(db_url) as verify:
        row = verify.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        assert row is not None, "bootstrap should have created the migrator role"

    # #137 — migrate up halts at the requires_superuser=True migration.
    up = runner.invoke(
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
    assert up.exit_code == 1, up.output
    assert "20260528180002" in up.output

    # #137 — apply-as resolves the skip.
    apply_as = runner.invoke(
        app,
        [
            "migrate",
            "apply-as",
            "postgres",
            "20260528180002",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert apply_as.exit_code == 0, apply_as.output

    with psycopg.connect(db_url) as verify:
        applied = {
            r[0]
            for r in verify.execute("SELECT version FROM tb_confiture ORDER BY version").fetchall()
        }
        assert applied == {"20260528180001", "20260528180002"}

        row = verify.execute(
            "SELECT applied_by FROM tb_confiture WHERE version = '20260528180002'"
        ).fetchone()
        assert row is not None
        assert row[0] == "postgres"  # #137 applied_by invariant


@pytest.mark.integration
def test_validate_check_function_uniqueness_under_018_config(
    smoke_env: tuple[str, str], tmp_path: Path
) -> None:
    db_url, role = smoke_env
    cfg = _write_config(tmp_path, db_url, role)

    # Two DDL files defining the same function.
    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True)
    body = (
        "CREATE OR REPLACE FUNCTION public.shared() "
        "RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n"
    )
    (schema_dir / "01_shared.sql").write_text(body)
    (schema_dir / "02_shared_dup.sql").write_text(body)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-function-uniqueness",
            "--config",
            str(cfg),
            "--ddl-dir",
            str(schema_dir),
        ],
    )
    # #136 — duplicate found, exit 1.
    assert result.exit_code == 1, result.output
    assert "func_001" in result.output


@pytest.mark.integration
def test_validate_check_ownership_coverage_flags_own_002(
    smoke_env: tuple[str, str], tmp_path: Path
) -> None:
    db_url, role = smoke_env
    cfg = _write_config(tmp_path, db_url, role)

    migrations_dir = tmp_path / "db" / "migrations"
    migrations_dir.mkdir(parents=True)
    # Bare ALTER OWNER on a pre-existing object — #137 own_002 ERROR case.
    (migrations_dir / "20260528180100_repair.up.sql").write_text(
        f"ALTER TABLE public.tb_legacy OWNER TO {role};\n"
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-ownership-coverage",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert result.exit_code == 1, result.output
    assert "own_002" in result.output
