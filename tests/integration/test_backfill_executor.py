"""The backfill between expand and contract is batched, observable and resumable.

200 000 rows, a batch size of 5 000: the executor must commit in bounded
batches (a progress report per committed batch, rows done never going
backwards), report each batch on the ``UpObserver`` seam, and pick up from a
checkpoint's cursor instead of starting over. Against the local database.
"""

from __future__ import annotations

from datetime import UTC, datetime

import psycopg

from confiture.core._migrator.events import UpEvent
from confiture.core.backfill import BackfillExecutor, BackfillSettings
from confiture.core.expand_contract import BackfillSpec
from confiture.core.step_runner import StepRecord

ROWS = 200_000
SPEC = BackfillSpec(
    table="orders", column="total", expression="id * 2", where_clause="total IS NULL"
)


def _table(conn: psycopg.Connection, filled_up_to: int = 0) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE orders (id integer PRIMARY KEY, total bigint)")
        cur.execute(
            "INSERT INTO orders (id, total) SELECT g, CASE WHEN g <= %s THEN g * 2 END "
            "FROM generate_series(1, %s) g",
            (filled_up_to, ROWS),
        )
    conn.commit()


def _filled(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM orders WHERE total = id * 2")
        return cur.fetchone()[0]


def test_two_hundred_thousand_rows_commit_in_bounded_batches(
    clean_test_db: psycopg.Connection,
) -> None:
    _table(clean_test_db)
    reports: list[tuple[int, int]] = []
    events: list[UpEvent] = []
    executor = BackfillExecutor(BackfillSettings(batch_size=5_000), on_event=events.append)

    rows = executor(clean_test_db, SPEC, None, lambda cursor, done: reports.append((cursor, done)))

    assert rows == ROWS
    assert _filled(clean_test_db) == ROWS
    assert len(reports) >= ROWS // 5_000  # one committed batch per report, batches bounded
    done = [d for _, d in reports]
    assert done == sorted(done) and done[-1] == ROWS
    progress = [e for e in events if e.kind == "backfill_progress"]
    assert len(progress) == len(reports)
    assert progress[-1].message.startswith("200000/200000")


def test_a_backfill_resumes_from_its_cursor(clean_test_db: psycopg.Connection) -> None:
    _table(clean_test_db, filled_up_to=ROWS // 2)
    with clean_test_db.cursor() as cur:  # the cursor is a ctid block: where row ROWS/2 + 1 lives
        cur.execute(
            "SELECT (ctid::text::point)[0]::int FROM orders WHERE id = %s", (ROWS // 2 + 1,)
        )
        block = cur.fetchone()[0]
    checkpoint = StepRecord(
        "20260101000000", 0, "backfill", "running", block, ROWS // 2, datetime.now(UTC)
    )
    reports: list[tuple[int, int]] = []
    executor = BackfillExecutor(BackfillSettings(batch_size=5_000))

    rows = executor(clean_test_db, SPEC, checkpoint, lambda c, d: reports.append((c, d)))

    assert _filled(clean_test_db) == ROWS
    # It did the second half only: the cursor skipped the blocks already done.
    assert rows == ROWS // 2
    assert reports[0][0] > block  # cursors move forward from the checkpoint
    assert reports[-1][1] == ROWS  # rows done continues the checkpoint's count
