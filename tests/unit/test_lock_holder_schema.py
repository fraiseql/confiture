"""The lock-holder table follows the tracking table's schema (#826).

The real-PostgreSQL behaviour is ``tests/integration/test_lock_holder_schema.py``.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from confiture.core._migrator.session import MigratorSession
from confiture.core.locking import LockConfig, MigrationLock
from confiture.sql_text import rendered


def _session_over(migration_table: str) -> MigratorSession:
    engine = MagicMock()
    engine.migration_table = migration_table
    return MigratorSession.attached(engine, Path("db/migrations"))


@pytest.mark.parametrize(
    ("tracking_table", "schema"),
    [("public.tb_confiture", "public"), ("ops.ledger", "ops"), ("tb_confiture", None)],
)
def test_the_session_lock_takes_the_tracking_tables_schema(
    tracking_table: str, schema: str | None
) -> None:
    lock = _session_over(tracking_table)._migration_lock(no_lock=False, lock_timeout=1000)
    assert lock.config.holder_schema == schema


def test_a_qualified_holder_is_written_qualified() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    MigrationLock(conn, LockConfig(holder_schema="public"))._clear_holder_metadata(7)
    statement = rendered(cursor.execute.call_args.args[0])
    assert '"public"."confiture_lock_holder"' in statement
