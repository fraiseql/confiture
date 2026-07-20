"""Real-database coverage for `verify-checksums` on a ledger-less DB (#182a).

The mocked unit tests pin the branch; this pins the *premise* — that a database
with no `tb_confiture` really does reach the guard rather than failing earlier.
#172 established that a real-DB test catches premise errors that mocked tests
wave through.

`clean_test_db` drops every table in `public`, so the connection it hands back
is exactly the state under test: reachable, no migration ledger.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

RAW_PSYCOPG_MARKERS = ('relation "', "LINE 1:")


@pytest.fixture
def cfg(tmp_path: Path, test_db_url: str) -> Path:
    p = tmp_path / "env.yaml"
    p.write_text(
        yaml.safe_dump({"name": "test", "database_url": test_db_url, "include_dirs": ["db/schema"]})
    )
    return p


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "20260101000000_init.up.sql").write_text("CREATE TABLE t (id int);")
    return d


def _run(cfg: Path, migrations_dir: Path, *extra: str):
    return runner.invoke(
        app,
        ["verify-checksums", "-c", str(cfg), "--migrations-dir", str(migrations_dir), *extra],
    )


def test_ledger_less_database_exits_2(
    clean_test_db: psycopg.Connection, cfg: Path, migrations_dir: Path
) -> None:
    result = _run(cfg, migrations_dir)

    assert result.exit_code == 2
    assert "is not present in this database" in result.output
    for marker in RAW_PSYCOPG_MARKERS:
        assert marker not in result.output


def test_ledger_less_database_with_allow_uninitialized_exits_0(
    clean_test_db: psycopg.Connection, cfg: Path, migrations_dir: Path
) -> None:
    result = _run(cfg, migrations_dir, "--allow-uninitialized")

    assert result.exit_code == 0
    assert "0 migrations recorded" in result.output


def test_present_but_empty_ledger_succeeds(
    clean_test_db: psycopg.Connection, cfg: Path, migrations_dir: Path
) -> None:
    """Absent != empty, against a real table.

    An empty `tb_confiture` means "initialized, nothing applied yet" — the
    command must succeed, not report a missing ledger.
    """
    with clean_test_db.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE tb_confiture (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                pk_confiture BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
                slug TEXT NOT NULL UNIQUE,
                version VARCHAR(255) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                execution_time_ms INTEGER,
                checksum VARCHAR(64),
                applied_by TEXT
            )
            """
        )
        clean_test_db.commit()

    result = _run(cfg, migrations_dir)

    assert result.exit_code == 0
    assert "All migration checksums verified" in result.output
    assert "no migration ledger" not in result.output.lower()


def test_deprecated_alias_on_ledger_less_database(
    clean_test_db: psycopg.Connection, cfg: Path, migrations_dir: Path
) -> None:
    result = runner.invoke(app, ["verify", "-c", str(cfg), "--migrations-dir", str(migrations_dir)])

    assert result.exit_code == 2
    assert "is not present in this database" in result.output
    assert "deprecated" in result.output.lower()
