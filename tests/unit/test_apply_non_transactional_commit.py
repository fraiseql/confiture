"""``Migrator.apply(commit=False)`` on a non-transactional migration is an error.

``commit=False`` means "I am inside a SAVEPOINT — do not persist". A
non-transactional migration cannot honour that: it commits the current
transaction and runs in autocommit. Silently doing so under a dry run persisted
everything tested before it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from confiture.core._migrator.engine import Migrator
from confiture.exceptions import MigrationError
from confiture.models.migration import Migration
from tests.unit._doubles import connection_double


class _ConcurrentIndex(Migration):
    version = "20260906000007"
    name = "concurrent_index"
    transactional = False

    def up(self) -> None:
        self.execute("CREATE INDEX CONCURRENTLY idx ON t (a)")

    def down(self) -> None:
        self.execute("DROP INDEX CONCURRENTLY idx")


def test_commit_false_on_non_transactional_migration_refuses() -> None:
    conn = connection_double()
    migrator = Migrator(connection=conn)
    migrator._record_migration = MagicMock()
    migration = _ConcurrentIndex(connection=conn)

    with pytest.raises(MigrationError, match="non-transactional"):
        migrator.apply(migration, skip_preconditions=True, commit=False)

    conn.commit.assert_not_called()
    migrator._record_migration.assert_not_called()
