"""The ledger's statements against a real server, under a schema-qualified ledger.

Each statement names the tracking table as one quoted identifier and carries its
values with it; these read and write a ``audit.tb_ledger`` ledger the way each
command does, so a statement that quoted, bound or qualified wrongly fails here
rather than in a deployment.
"""

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture.core.checksum import MigrationChecksumVerifier
from confiture.core.ledger import ledger_is_empty, recorded_versions
from confiture.core.migrator import MigratorSession

pytestmark = pytest.mark.integration

LEDGER = "audit.tb_ledger"
VERSIONS = ("20260101000001", "20260101000002")


def _project(tmp_path: Path) -> Path:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for index, version in enumerate(VERSIONS):
        (migrations / f"{version}_t{index}.up.sql").write_text(f"CREATE TABLE t{index} (id int);\n")
        (migrations / f"{version}_t{index}.down.sql").write_text(f"DROP TABLE t{index};\n")
    return migrations


def _database(factory: Callable[[str], str]) -> str:
    url = factory("confiture_ledger")
    with psycopg.connect(url) as conn:
        conn.execute("CREATE SCHEMA audit")
    return url


@pytest.fixture
def applied(fresh_database_factory: Callable[[str], str], tmp_path: Path) -> tuple[str, Path]:
    """Both migrations applied, recorded in ``audit.tb_ledger``."""
    url = _database(fresh_database_factory)
    migrations = _project(tmp_path)
    with MigratorSession(
        None, migrations, database_url_override=url, migration_table_override=LEDGER
    ) as session:
        assert session.up().success
    return url, migrations


def test_recorded_versions_reads_a_qualified_ledger(applied: tuple[str, Path]) -> None:
    url, _ = applied
    with psycopg.connect(url) as conn:
        assert recorded_versions(conn, LEDGER) == set(VERSIONS)


def test_ledger_is_empty_reads_a_qualified_ledger(applied: tuple[str, Path]) -> None:
    url, _ = applied
    with psycopg.connect(url) as conn:
        assert ledger_is_empty(conn, LEDGER) is False
        conn.execute("DELETE FROM audit.tb_ledger")
        assert ledger_is_empty(conn, LEDGER) is True


def test_update_checksum_rewrites_one_row(applied: tuple[str, Path]) -> None:
    url, _ = applied
    with psycopg.connect(url) as conn:
        MigrationChecksumVerifier(conn, migration_table=LEDGER).update_checksum(
            VERSIONS[0], "restamped"
        )
        rows = conn.execute(
            "SELECT version, checksum = 'restamped' FROM audit.tb_ledger ORDER BY version"
        ).fetchall()

    assert rows == [(VERSIONS[0], True), (VERSIONS[1], False)]


def test_baseline_from_db_copies_a_qualified_source_ledger(
    applied: tuple[str, Path], fresh_database_factory: Callable[[str], str]
) -> None:
    source_url, migrations = applied
    target_url = _database(fresh_database_factory)
    with MigratorSession(
        None, migrations, database_url_override=target_url, migration_table_override=LEDGER
    ) as session:
        session.migrator.initialize()
        result = session.migrator.baseline_from_db(source_url, migrations, source_table=LEDGER)

    assert sorted(row["version"] for row in result["copied"]) == list(VERSIONS)
    with psycopg.connect(target_url) as conn:
        assert recorded_versions(conn, LEDGER) == set(VERSIONS)


def test_a_non_transactional_rollback_deletes_its_row(
    fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    url = _database(fresh_database_factory)
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    version = VERSIONS[0]
    (migrations / f"{version}_ix.up.sql").write_text(
        "CREATE TABLE t (id int);\nCREATE INDEX CONCURRENTLY ix_t ON t (id);\n"
    )
    (migrations / f"{version}_ix.down.sql").write_text(
        "DROP INDEX CONCURRENTLY ix_t;\nDROP TABLE t;\n"
    )
    with MigratorSession(
        None, migrations, database_url_override=url, migration_table_override=LEDGER
    ) as session:
        assert session.up().success
        assert session.down(steps=1).success

    with psycopg.connect(url) as conn:
        assert recorded_versions(conn, LEDGER) == set()
