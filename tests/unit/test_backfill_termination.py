"""``backfill_column`` terminates on its own.

The loop used to stop only when an ``UPDATE … LIMIT batch_size`` touched zero
rows. With the default ``where_clause="TRUE"`` that never happens: every batch
re-selects the first *batch_size* rows, forever. Termination must come from
the iteration itself — the table's block range — not from the predicate.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from confiture.core.large_tables import BatchConfig, BatchedMigration

BATCH = 1000
MAX_UPDATES = 50


class _EndlessCursor:
    """Every UPDATE reports a full batch; COUNT(*) says 25,000 rows over 10 blocks."""

    def __init__(self) -> None:
        self.updates = 0
        self.rowcount = BATCH
        self._last = ""

    def execute(self, sql, params=None):
        self._last = str(sql).lower()
        if "update" in self._last:
            self.updates += 1
            if self.updates > MAX_UPDATES:
                raise RuntimeError("backfill_column did not terminate")
        return self

    def fetchone(self):
        if "pg_relation_size" in self._last or "relpages" in self._last:
            return (10,)
        return (25_000,)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def test_default_predicate_terminates() -> None:
    cursor = _EndlessCursor()
    conn = MagicMock()
    conn.cursor.return_value = cursor
    batched = BatchedMigration(conn, BatchConfig(batch_size=BATCH, sleep_between_batches=0))

    progress = batched.backfill_column("orders", "total_cents", "subtotal + tax")

    assert cursor.updates <= MAX_UPDATES
    assert progress.current_batch == progress.total_batches == cursor.updates
    assert progress.processed_rows == cursor.updates * BATCH
