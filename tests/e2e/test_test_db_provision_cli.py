"""E2E: `confiture test-db provision-template` (DDL path) through the CLI (#159).

Exercises the Typer command → SchemaBuilder.build → TestDbProvisioner →
psql-applier → error-handler wiring that the core-level tests bypass:

- a COPY-bearing schema provisions successfully (exit 0, rows land);
- a broken schema reports a *syntax* failure, not "the schema directory doesn't
  exist" (Defect C, end to end through `fail()`).

Requires a reachable local PostgreSQL and `psql` on PATH; skips cleanly otherwise.
"""

from __future__ import annotations

import os
import shutil

import psycopg
import psycopg.sql
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.temp_database import _maintenance_url, _replace_dbname

runner = CliRunner()

_TEMPLATE = "confiture_e2e_copy_tmpl"


def _server_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


def _drop_template() -> None:
    with psycopg.connect(_maintenance_url(_server_url()), autocommit=True) as conn:
        conn.execute(
            psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                psycopg.sql.Identifier(_TEMPLATE)
            )
        )


def _combined_output(result) -> str:
    """stdout plus stderr (the error boundary writes to a stderr console)."""
    out = result.output or ""
    try:
        if result.stderr:
            out += result.stderr
    except (ValueError, AttributeError):
        # Older Click mixes stderr into output; result.stderr then raises.
        pass
    return out.lower()


@pytest.fixture
def project(tmp_path):
    if shutil.which("psql") is None:
        pytest.skip("psql not on PATH")
    try:
        with psycopg.connect(_maintenance_url(_server_url()), autocommit=True):
            pass
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")

    schema_dir = tmp_path / "db" / "schema" / "10_reference"
    schema_dir.mkdir(parents=True)
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "test.yaml").write_text(
        f"name: test\ninclude_dirs:\n  - db/schema\nexclude_dirs: []\n"
        f"database_url: {_server_url()}\n"
    )

    _drop_template()
    try:
        yield tmp_path, schema_dir
    finally:
        _drop_template()


def test_provision_template_copy_schema_via_cli(project) -> None:
    tmp_path, schema_dir = project
    (schema_dir / "country.sql").write_text(
        "CREATE TABLE country (code text PRIMARY KEY, name text);\n"
        "COPY country (code, name) FROM stdin;\n"
        "FR\tFrance\n"
        "DE\tGermany\n"
        "\\.\n"
    )

    result = runner.invoke(
        app,
        [
            "test-db",
            "provision-template",
            "--template",
            _TEMPLATE,
            "--env",
            "test",
            "--project-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, _combined_output(result)

    with psycopg.connect(_replace_dbname(_server_url(), _TEMPLATE), autocommit=True) as conn:
        count = conn.execute("SELECT count(*) FROM country").fetchone()[0]
    assert count == 2


def test_broken_schema_reports_syntax_not_missing_dir(project) -> None:
    tmp_path, schema_dir = project
    # Unterminated CREATE TABLE → psql reports a syntax error.
    (schema_dir / "broken.sql").write_text("CREATE TABLE broken (id int")

    result = runner.invoke(
        app,
        [
            "test-db",
            "provision-template",
            "--template",
            _TEMPLATE,
            "--env",
            "test",
            "--project-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    out = _combined_output(result)
    # Defect C: an apply/syntax failure is NOT mislabeled as a missing schema dir.
    assert "mkdir" not in out  # the SCHEMA_DIR_NOT_FOUND remediation must be absent
    assert "syntax" in out  # the real cause is surfaced
