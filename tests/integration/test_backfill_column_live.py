"""``backfill_column`` on a real table larger than one batch."""

from __future__ import annotations

import psycopg
import pytest

from confiture.core.large_tables import BatchConfig, BatchedMigration

ROWS = 2_500


@pytest.mark.integration
def test_backfill_terminates_and_updates_every_row(clean_test_db, test_db_url: str) -> None:
    with psycopg.connect(test_db_url) as conn:
        conn.execute("CREATE TABLE orders (id INT PRIMARY KEY, subtotal INT, tax INT, total INT)")
        conn.execute(
            "INSERT INTO orders (id, subtotal, tax) SELECT g, g * 10, g FROM generate_series(1, %s) g",
            (ROWS,),
        )
        conn.commit()

        batched = BatchedMigration(conn, BatchConfig(batch_size=1000, sleep_between_batches=0))
        progress = batched.backfill_column("orders", "total", "subtotal + tax")

        updated = conn.execute(
            "SELECT count(*) FROM orders WHERE total = subtotal + tax"
        ).fetchone()[0]

    assert updated == ROWS
    assert progress.processed_rows == ROWS
    assert progress.total_batches >= 3
    assert progress.current_batch == progress.total_batches
