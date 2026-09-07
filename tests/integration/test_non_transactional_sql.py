"""Non-transactional SQL-file migrations.

``CREATE INDEX CONCURRENTLY`` cannot run inside a transaction block. A
``.up.sql`` carrying two of them was executed as one multi-statement string,
which PostgreSQL wraps in an implicit transaction even under autocommit — so it
failed. And ``dry_run_execute`` handed such a migration to the autocommit apply
path, which committed the SAVEPOINT's transaction on its way through.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from confiture.core.migrator import MigratorSession

V1, V2 = "20260906000005", "20260906000006"


def _migrations(tmp_path: Path) -> Path:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / f"{V1}_create_things.up.sql").write_text(
        "CREATE TABLE things (id INT PRIMARY KEY, a INT, b INT);\n"
    )
    (migrations / f"{V1}_create_things.down.sql").write_text("DROP TABLE things;\n")
    (migrations / f"{V2}_index_things.up.sql").write_text(
        "CREATE INDEX CONCURRENTLY idx_things_a ON things (a);\n"
        "CREATE INDEX CONCURRENTLY idx_things_b ON things (b);\n"
    )
    (migrations / f"{V2}_index_things.down.sql").write_text(
        "DROP INDEX CONCURRENTLY idx_things_a;\nDROP INDEX CONCURRENTLY idx_things_b;\n"
    )
    return migrations


def _state(url: str) -> dict[str, object]:
    with psycopg.connect(url) as conn:
        indexes = conn.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'things' ORDER BY 1"
        ).fetchall()
        table = conn.execute("SELECT to_regclass('public.things') IS NOT NULL").fetchone()[0]
        ledger = conn.execute("SELECT version FROM tb_confiture ORDER BY 1").fetchall()
    return {
        "indexes": [r[0] for r in indexes],
        "table": table,
        "ledger": [r[0] for r in ledger],
    }


@pytest.mark.integration
def test_two_concurrent_index_builds_in_one_file_apply(
    clean_test_db, test_db_url: str, tmp_path: Path
) -> None:
    migrations = _migrations(tmp_path)
    with MigratorSession(None, migrations, database_url_override=test_db_url) as s:
        result = s.up()
    assert result.success is True, result.errors
    assert [m.version for m in result.migrations_applied] == [V1, V2]
    state = _state(test_db_url)
    assert state["ledger"] == [V1, V2]
    assert state["indexes"] == ["idx_things_a", "idx_things_b", "things_pkey"]


@pytest.mark.integration
def test_dry_run_execute_skips_non_transactional_and_commits_nothing(
    clean_test_db, test_db_url: str, tmp_path: Path
) -> None:
    migrations = _migrations(tmp_path)
    with MigratorSession(None, migrations, database_url_override=test_db_url) as s:
        result = s.up(dry_run_execute=True)
    assert result.success is True, result.errors
    assert [m.version for m in result.migrations_applied] == [V1]
    assert V2 in result.skipped
    assert any(V2 in w and "transactional" in w for w in result.warnings), result.warnings
    assert _state(test_db_url) == {"indexes": [], "table": False, "ledger": []}


@pytest.mark.integration
def test_non_transactional_down_rolls_back(clean_test_db, test_db_url: str, tmp_path: Path) -> None:
    migrations = _migrations(tmp_path)
    with MigratorSession(None, migrations, database_url_override=test_db_url) as s:
        assert s.up().success
        result = s.down(steps=1)
    assert result.success is True, result.error
    state = _state(test_db_url)
    assert state["ledger"] == [V1]
    assert state["indexes"] == ["things_pkey"]
