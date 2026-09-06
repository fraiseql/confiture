"""``Migrator.migrate_up()`` runs the one apply loop — SQL-file migrations included.

The engine used to carry a third copy of the loop (``apply.migrate_up_internal``)
that imported every migration file as a Python module, so a ``.up.sql``
migration could not be applied through it. It now runs ``MigratorSession.up()``
attached to the engine's own connection.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from confiture.core.checksum import ChecksumVerificationError
from confiture.core.migrator import Migrator

VERSION = "20260906000004"


def _migrations(tmp_path: Path) -> Path:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / f"{VERSION}_create_widgets.up.sql").write_text(
        "CREATE TABLE widgets (id INT PRIMARY KEY);\n"
    )
    (migrations / f"{VERSION}_create_widgets.down.sql").write_text("DROP TABLE widgets;\n")
    return migrations


@pytest.mark.integration
def test_migrate_up_applies_sql_file_migrations(clean_test_db, test_db_url: str, tmp_path) -> None:
    migrations = _migrations(tmp_path)
    with psycopg.connect(test_db_url) as conn:
        applied = Migrator(connection=conn).migrate_up(migrations_dir=migrations)
        assert applied == [VERSION]
        assert conn.execute("SELECT to_regclass('public.widgets') IS NOT NULL").fetchone()[0]
        # Idempotent: a second call finds nothing pending.
        assert Migrator(connection=conn).migrate_up(migrations_dir=migrations) == []


@pytest.mark.integration
def test_migrate_up_verifies_checksums_like_the_session(
    clean_test_db, test_db_url: str, tmp_path
) -> None:
    migrations = _migrations(tmp_path)
    with psycopg.connect(test_db_url) as conn:
        Migrator(connection=conn).migrate_up(migrations_dir=migrations)
        up = migrations / f"{VERSION}_create_widgets.up.sql"
        up.write_text(up.read_text() + "-- edited after apply\n")
        with pytest.raises(ChecksumVerificationError):
            Migrator(connection=conn).migrate_up(migrations_dir=migrations)
