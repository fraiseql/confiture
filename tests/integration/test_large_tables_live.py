"""The batched operations and the online index builder, on a real table.

The table's name needs quotes (a capital) and is schema-qualified, and the
author's raw fragments (a type, a default, a predicate with ``%``, a transform)
reach the server as written.
"""

import psycopg
import pytest

from confiture.core.large_tables import (
    BatchConfig,
    BatchedMigration,
    OnlineIndexBuilder,
    TableSizeEstimator,
)

ROWS = 250
TABLE = "public.Orders"


@pytest.fixture
def orders(clean_test_db, test_db_url: str):
    with psycopg.connect(test_db_url) as conn:
        conn.execute('CREATE TABLE public."Orders" (id INT PRIMARY KEY, email TEXT, total INT)')
        conn.execute(
            'INSERT INTO public."Orders" (id, email, total) '
            "SELECT g, 'User' || g || '@Example.org', g FROM generate_series(1, %s) g",
            (ROWS,),
        )
        conn.commit()
        yield conn


def _batched(conn: psycopg.Connection) -> BatchedMigration:
    return BatchedMigration(conn, BatchConfig(batch_size=100, sleep_between_batches=0))


@pytest.mark.integration
def test_a_column_is_added_and_filled_in_batches(orders: psycopg.Connection) -> None:
    progress = _batched(orders).add_column_with_default(TABLE, "status", "TEXT", "'active'")

    filled = orders.execute(
        """SELECT count(*) FROM public."Orders" WHERE status = 'active'"""
    ).fetchone()[0]
    default = orders.execute(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name = 'Orders' AND column_name = 'status'"
    ).fetchone()[0]
    assert (filled, progress.processed_rows) == (ROWS, ROWS)
    assert default == "'active'::text"


@pytest.mark.integration
def test_rows_are_deleted_in_batches_by_a_raw_predicate(orders: psycopg.Connection) -> None:
    progress = _batched(orders).delete_in_batches(TABLE, "id % 2 = 0")

    left = orders.execute('SELECT count(*) FROM public."Orders"').fetchone()[0]
    assert (left, progress.processed_rows) == (ROWS // 2, ROWS // 2)


@pytest.mark.integration
def test_rows_are_copied_with_a_transform(orders: psycopg.Connection) -> None:
    orders.execute('CREATE TABLE public."Orders_new" (id INT PRIMARY KEY, email TEXT, total INT)')
    orders.commit()

    progress = _batched(orders).copy_to_new_table(
        TABLE, "public.Orders_new", transform={"email": "lower(email)"}, where_clause="total > 50"
    )

    copied = orders.execute(
        """SELECT count(*), count(*) FILTER (WHERE email = lower(email))
           FROM public."Orders_new" """
    ).fetchone()
    assert copied == (ROWS - 50, ROWS - 50)
    assert progress.processed_rows == ROWS - 50


@pytest.mark.integration
def test_an_index_is_built_rebuilt_and_dropped_online(orders: psycopg.Connection) -> None:
    builder = OnlineIndexBuilder(orders)

    name = builder.create_index_concurrently(
        TABLE,
        ["email", "lower(email)"],
        index_name="Orders_email_idx",
        unique=True,
        where="total > 10",
        include=["total"],
    )
    definition = orders.execute(
        "SELECT pg_get_indexdef('public.\"Orders_email_idx\"'::regclass)"
    ).fetchone()[0]
    valid = builder.check_index_validity(name)
    orders.commit()
    builder.reindex_concurrently("public.Orders_email_idx")
    builder.drop_index_concurrently("public.Orders_email_idx")
    gone = orders.execute("SELECT to_regclass('public.\"Orders_email_idx\"')").fetchone()[0]

    assert definition == (
        'CREATE UNIQUE INDEX "Orders_email_idx" ON public."Orders" USING btree '
        "(email, lower(email)) INCLUDE (total) WHERE (total > 10)"
    )
    assert valid is True
    assert gone is None


@pytest.mark.integration
def test_an_exact_count_reads_a_raw_predicate(orders: psycopg.Connection) -> None:
    assert TableSizeEstimator(orders).get_exact_row_count(TABLE, "id % 5 = 0") == ROWS // 5
