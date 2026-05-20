"""Integration test backing docs/guides/legacy-bootstrap.md.

The legacy-bootstrap guide promises a specific recipe — vendor the existing
migration files, run ``confiture migrate baseline --through <version>``, and
``migrate status`` reports them as applied with no pending work.

If the CLI surface or baseline semantics change, this test should fail before
the docs go stale.

Requires DATABASE_URL to point at a writable Postgres. Skipped otherwise.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

pytestmark = pytest.mark.integration

runner = CliRunner()


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — skipping legacy-bootstrap integration test")
    return url


@pytest.fixture
def clean_db(db_url: str):
    """Wipe tb_confiture and any tables created by the test before/after."""
    conn = psycopg.connect(db_url, autocommit=True)
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS tb_confiture CASCADE")
        cur.execute("DROP TABLE IF EXISTS legacy_orders CASCADE")
        cur.execute("DROP TABLE IF EXISTS legacy_users CASCADE")
    yield conn
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS tb_confiture CASCADE")
        cur.execute("DROP TABLE IF EXISTS legacy_orders CASCADE")
        cur.execute("DROP TABLE IF EXISTS legacy_users CASCADE")
    conn.close()


# The four migration pairs that simulate "history applied by hand with psql".
# The names match what docs/guides/legacy-bootstrap.md tells the reader to vendor.
LEGACY_MIGRATIONS: list[tuple[str, str, str, str]] = [
    (
        "001",
        "create_users",
        "CREATE TABLE legacy_users (id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL);",
        "DROP TABLE legacy_users;",
    ),
    (
        "002",
        "create_orders",
        "CREATE TABLE legacy_orders (id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES legacy_users(id));",
        "DROP TABLE legacy_orders;",
    ),
    (
        "003",
        "add_user_email",
        "ALTER TABLE legacy_users ADD COLUMN email TEXT;",
        "ALTER TABLE legacy_users DROP COLUMN email;",
    ),
    (
        "004",
        "add_user_preferences",
        "ALTER TABLE legacy_users ADD COLUMN preferences JSONB NOT NULL DEFAULT '{}'::JSONB;",
        "ALTER TABLE legacy_users DROP COLUMN preferences;",
    ),
]


def _write_migration_files(migrations_dir: Path) -> None:
    """Write the four legacy migration pairs to disk in Confiture's naming convention."""
    migrations_dir.mkdir(parents=True, exist_ok=True)
    for version, name, up_sql, down_sql in LEGACY_MIGRATIONS:
        (migrations_dir / f"{version}_{name}.up.sql").write_text(up_sql + "\n")
        (migrations_dir / f"{version}_{name}.down.sql").write_text(down_sql + "\n")


def _apply_migrations_by_hand(conn: psycopg.Connection) -> None:
    """Replicate the operator's pre-Confiture workflow — run the SQL directly."""
    with conn.cursor() as cur:
        for _version, _name, up_sql, _down_sql in LEGACY_MIGRATIONS:
            cur.execute(up_sql)
    conn.commit()


def test_baseline_recipe_works_against_pre_existing_history(
    clean_db: psycopg.Connection, db_url: str, tmp_path: Path
) -> None:
    """The exact CLI sequence in docs/guides/legacy-bootstrap.md must work end-to-end.

    Scenario: a Postgres at version 004 (applied by hand). The operator vendors
    the migration files, writes a Confiture environment, runs
    ``confiture migrate baseline --through 004_add_user_preferences``,
    and ``migrate status`` reports four applied / zero pending.
    """
    # 1. Simulate "applied by hand with psql".
    _apply_migrations_by_hand(clean_db)

    # 2. Vendor the migration files in Confiture's naming convention.
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    migrations_dir = project_dir / "db" / "migrations"
    _write_migration_files(migrations_dir)

    # 3. Write the environment YAML the guide tells the operator to write.
    env_dir = project_dir / "db" / "environments"
    env_dir.mkdir(parents=True)
    env_file = env_dir / "production.yaml"
    env_file.write_text(
        yaml.dump(
            {
                "name": "production",
                "database_url": db_url,
                "include_dirs": ["db/schema"],
                "migration": {"tracking_table": "tb_confiture"},
            }
        )
    )

    # Working directory matters — Typer commands resolve `db/migrations` relative to cwd.
    old_cwd = Path.cwd()
    try:
        os.chdir(project_dir)

        # 4. Run baseline through 004.
        result = runner.invoke(
            app,
            ["migrate", "baseline", "--through", "004", "-c", str(env_file)],
        )
        assert result.exit_code == 0, f"baseline failed:\n{result.output}"
        assert "Marked 4 migration(s) as applied" in result.output

        # 5. Confirm `migrate status --format json` reports 4 applied / 0 pending.
        status = runner.invoke(
            app,
            ["migrate", "status", "-c", str(env_file), "--format", "json"],
        )
        assert status.exit_code == 0, f"status failed:\n{status.output}"
        payload = json.loads(status.stdout)
        # Status payload shape: {"applied": [...], "pending": [...], ...}
        assert len(payload.get("applied", [])) == 4
        assert payload.get("pending", []) == []

        # 6. Sanity: re-running baseline is a no-op (rows already exist).
        rerun = runner.invoke(
            app,
            ["migrate", "baseline", "--through", "004", "-c", str(env_file)],
        )
        assert rerun.exit_code == 0
        assert "skipped 4 already applied" in rerun.output
    finally:
        os.chdir(old_cwd)


def test_envsubst_secret_substitution_pattern(
    clean_db: psycopg.Connection, db_url: str, tmp_path: Path
) -> None:
    """The prerequisites doc points users at ``envsubst`` to inject the DSN.

    Verify the documented workflow actually round-trips: write a template
    with the literal ``${DATABASE_URL}``, run ``envsubst`` over it, hand the
    rendered YAML to confiture.  If this stops working the prerequisites
    doc has gone stale.
    """
    if shutil.which("envsubst") is None:
        pytest.skip("envsubst not installed — skipping shell-substitution path")

    _apply_migrations_by_hand(clean_db)

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    migrations_dir = project_dir / "db" / "migrations"
    _write_migration_files(migrations_dir)
    env_dir = project_dir / "db" / "environments"
    env_dir.mkdir(parents=True)

    # Template uses the literal ${DATABASE_URL} the docs tell readers to write.
    template = env_dir / "production.template.yaml"
    template.write_text(
        "name: production\n"
        "database_url: ${DATABASE_URL}\n"
        "include_dirs:\n"
        "  - db/schema\n"
        "migration:\n"
        "  tracking_table: tb_confiture\n"
    )

    # The docs say: run envsubst before invoking the CLI.
    rendered = env_dir / "production.yaml"
    with rendered.open("w") as out:
        subprocess.run(
            ["envsubst"],
            stdin=template.open(),
            stdout=out,
            env={**os.environ, "DATABASE_URL": db_url},
            check=True,
        )

    # Confirm the rendered file no longer contains ${DATABASE_URL}.
    assert "${DATABASE_URL}" not in rendered.read_text()
    assert db_url in rendered.read_text()

    old_cwd = Path.cwd()
    try:
        os.chdir(project_dir)
        result = runner.invoke(
            app,
            ["migrate", "baseline", "--through", "004", "-c", str(rendered)],
        )
        assert result.exit_code == 0, (
            f"baseline with envsubst-rendered YAML failed:\n{result.output}"
        )
        assert "Marked 4 migration(s) as applied" in result.output
    finally:
        os.chdir(old_cwd)
