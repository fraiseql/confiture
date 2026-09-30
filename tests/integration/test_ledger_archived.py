"""A ledger row archived into a squashed baseline is history (#539).

``migrate squash`` moves old migration files out of the migrations directory and
marks their ledger rows ``archived_into`` rather than deleting them, so each keeps
its ``applied_at``, checksum and role. Such a row is applied, and it is history:
never pending, never checked against a file, never rolled back. A ledger created
before the column existed reads the same, whatever command reads it first.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture.core.migrator import MigratorSession

pytestmark = pytest.mark.integration

VERSIONS = ("20260101000001", "20260101000002", "20260101000003")


@pytest.fixture
def squashed(fresh_database_factory: Callable[[str], str], tmp_path: Path) -> tuple[str, Path]:
    """Three applied migrations; the first two archived into ``20260101000002``."""
    url = fresh_database_factory("confiture_arch")
    migrations = tmp_path / "migrations"
    archive = migrations / "archive"
    archive.mkdir(parents=True)
    for index, version in enumerate(VERSIONS):
        (migrations / f"{version}_t{index}.up.sql").write_text(f"CREATE TABLE t{index} (id int);\n")
        (migrations / f"{version}_t{index}.down.sql").write_text(f"DROP TABLE t{index};\n")
    with MigratorSession(None, migrations, database_url_override=url) as session:
        assert session.up().success
    for index, version in enumerate(VERSIONS[:2]):
        for suffix in (".up.sql", ".down.sql"):
            name = f"{version}_t{index}{suffix}"
            (migrations / name).rename(archive / name)
    with psycopg.connect(url) as conn:
        conn.execute(
            "UPDATE tb_confiture SET archived_into = %s WHERE version = ANY(%s)",
            (VERSIONS[1], list(VERSIONS[:2])),
        )
    return url, migrations


def test_the_ledger_carries_the_column(squashed: tuple[str, Path]) -> None:
    url, _ = squashed
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT version, archived_into FROM tb_confiture ORDER BY version"
        ).fetchall()

    assert rows == [(VERSIONS[0], VERSIONS[1]), (VERSIONS[1], VERSIONS[1]), (VERSIONS[2], None)]


def test_an_archived_row_is_never_pending(squashed: tuple[str, Path]) -> None:
    url, migrations = squashed
    with MigratorSession(None, migrations, database_url_override=url) as session:
        status = session.status()

    assert status.summary == {"applied": 1, "pending": 0, "total": 1}


def test_an_archived_row_is_not_checked_against_a_file(squashed: tuple[str, Path]) -> None:
    url, migrations = squashed
    with MigratorSession(None, migrations, database_url_override=url) as session:
        result = session.up(verify_checksums=True)

    assert result.success is True
    assert result.checksums_verified is True
    assert result.migrations_applied == []


def test_down_never_reaches_an_archived_row(squashed: tuple[str, Path]) -> None:
    url, migrations = squashed
    with MigratorSession(None, migrations, database_url_override=url) as session:
        result = session.down(steps=3)

    assert [m.version for m in result.migrations_rolled_back] == [VERSIONS[2]]
    with psycopg.connect(url) as conn:
        kept = conn.execute("SELECT version FROM tb_confiture ORDER BY version").fetchall()
    assert kept == [(VERSIONS[0],), (VERSIONS[1],)]


def test_the_current_revision_is_the_newest_live_row(squashed: tuple[str, Path]) -> None:
    url, migrations = squashed
    with psycopg.connect(url) as conn:
        conn.execute(
            "UPDATE tb_confiture SET applied_at = now() + interval '1 day' WHERE version = %s",
            (VERSIONS[0],),
        )
    with MigratorSession(None, migrations, database_url_override=url) as session:
        current = session.current_revision()

    assert current is not None
    assert current.version == VERSIONS[2]


def test_a_ledger_from_before_the_column_reads_unchanged(squashed: tuple[str, Path]) -> None:
    url, migrations = squashed
    with psycopg.connect(url) as conn:
        conn.execute("ALTER TABLE tb_confiture DROP COLUMN archived_into")
    with MigratorSession(None, migrations, database_url_override=url) as session:
        status = session.status()

    assert status.summary == {"applied": 1, "pending": 0, "total": 1}


def test_initialising_an_older_ledger_adds_the_column(squashed: tuple[str, Path]) -> None:
    url, migrations = squashed
    with psycopg.connect(url) as conn:
        conn.execute("ALTER TABLE tb_confiture DROP COLUMN archived_into")
    with MigratorSession(None, migrations, database_url_override=url) as session:
        session.up()
    with psycopg.connect(url) as conn:
        found = conn.execute(
            "SELECT count(*) FROM tb_confiture WHERE archived_into IS NULL"
        ).fetchone()

    assert found == (3,)
