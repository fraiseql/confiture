"""The batched backfill between expand and contract: bounded, observable, resumable.

A thin executor over :class:`~confiture.core.large_tables.BatchedMigration`
— the ctid-batched ``UPDATE`` that already commits per batch and can start
from an offset. This module adds what the runner needs: settings from the
environment config (``migration.backfill``), a checkpoint written after every
committed batch, a ``backfill_progress`` event per batch on the ``UpObserver``
seam, resumption from a checkpoint's cursor, and a guard that pauses between
batches while other sessions wait for a lock on the table.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from confiture.core._migrator.events import UpObserver, emit
from confiture.core.large_tables import BatchConfig, BatchedMigration

if TYPE_CHECKING:
    from confiture.core.expand_contract import BackfillSpec
    from confiture.core.step_runner import StepRecord

DEFAULT_BATCH_SIZE = 5_000
MAX_WAITER_PAUSES = 100


@dataclass(frozen=True)
class BackfillSettings:
    """How a backfill runs: rows per committed batch, and the lock-waiter guard.

    ``max_lock_ms`` is the pause between batches while another session waits
    for a lock on the table — the backfill yields rather than queue behind it;
    ``None`` disables the guard.
    """

    batch_size: int = DEFAULT_BATCH_SIZE
    max_lock_ms: int | None = None
    sleep_between_batches: float = 0.0


def waiters_on(connection: Any, table: str) -> int:
    """How many other sessions currently wait for a lock on ``table``."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
            "WHERE NOT l.granted AND l.relation = %s::regclass AND a.pid <> pg_backend_pid()",
            (table,),
        )
        return int(cur.fetchone()[0])


def yield_to_waiters(
    connection: Any,
    table: str,
    max_lock_ms: int | None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Pause ``max_lock_ms`` at a time while sessions wait on ``table``; return the pauses taken."""
    if not max_lock_ms:
        return 0
    pauses = 0
    while pauses < MAX_WAITER_PAUSES and waiters_on(connection, table) > 0:
        sleep(max_lock_ms / 1000)
        pauses += 1
    return pauses


class BackfillExecutor:
    """Callable with the runner's ``Backfiller`` signature."""

    def __init__(
        self,
        settings: BackfillSettings | None = None,
        *,
        on_event: UpObserver | None = None,
        migration: str | None = None,
    ) -> None:
        self.settings = settings or BackfillSettings()
        self._on_event = on_event
        self._migration = migration

    def __call__(
        self,
        connection: Any,
        spec: BackfillSpec,
        checkpoint: StepRecord | None,
        progress: Callable[[int, int], None],
    ) -> int:
        """Backfill ``spec`` from ``checkpoint``'s cursor (or the start); return the rows updated."""
        start_block = checkpoint.batch_cursor if checkpoint is not None else None
        done_so_far = checkpoint.rows_done if checkpoint is not None else 0
        state = {"done": done_so_far}

        def report(done: int, total: int) -> None:
            state["done"] = done_so_far + done
            emit(
                self._on_event,
                "backfill_progress",
                version=self._migration,
                name=spec.table,
                message=f"{done}/{total} rows",
            )

        def committed(next_block: int) -> None:
            progress(next_block, state["done"])
            yield_to_waiters(connection, spec.table, self.settings.max_lock_ms)

        batched = BatchedMigration(
            connection,
            BatchConfig(
                batch_size=self.settings.batch_size,
                sleep_between_batches=self.settings.sleep_between_batches,
                progress_callback=report,
                block_callback=committed,
            ),
        )
        result = batched.backfill_column(
            spec.table, spec.column, spec.expression, spec.where_clause, start_block=start_block
        )
        return result.processed_rows
