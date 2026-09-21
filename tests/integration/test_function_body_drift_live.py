"""Integration test: function body drift + unified diff against real prosrc.

Reproduces the epic's core scenario — a function hot-patched directly in the
database (``CREATE OR REPLACE`` on prod) while the committed source SQL still
carries the old body — and asserts that the detector surfaces both bodies and a
readable, line-oriented unified diff built from the live ``pg_proc.prosrc``.

Requires a PostgreSQL server at ``CONFITURE_TEST_DB_URL``
(routing rule in ``tests/conftest.py``).
"""

from __future__ import annotations

import psycopg
import pytest

from confiture.core.function_body_drift import FunctionBodyDriftDetector
from confiture.core.function_signature_drift import declared_routines, live_routines

# The committed source — what the repo believes the function body is.
_SOURCE_SQL = """
CREATE OR REPLACE FUNCTION public.calc_total(amount numeric)
RETURNS numeric
LANGUAGE plpgsql
AS $$
BEGIN
    -- Apply 20% VAT
    RETURN amount * 1.20;
END;
$$;
"""

# The live (hot-patched) body — VAT rate quietly changed in prod.
_LIVE_HOTPATCH_SQL = """
CREATE OR REPLACE FUNCTION public.calc_total(amount numeric)
RETURNS numeric
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN amount * 1.196;
END;
$$;
"""


@pytest.fixture
def _hotpatched_function(
    test_db_connection: psycopg.Connection,
) -> psycopg.Connection:
    """Install the hot-patched function; drop it afterwards."""
    conn = test_db_connection
    try:
        with conn.cursor() as cur:
            cur.execute(_LIVE_HOTPATCH_SQL)
        conn.commit()
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute("DROP FUNCTION IF EXISTS public.calc_total(numeric);")
        conn.commit()


def test_body_drift_unified_diff_from_live_prosrc(
    _hotpatched_function: psycopg.Connection,
) -> None:
    conn = _hotpatched_function

    # Source side: the committed DDL, read into the schema model.
    declared = declared_routines(_SOURCE_SQL)
    assert [routine.name for routine in declared] == ["calc_total"]

    # Live side: the real prosrc, read back out of the database.
    report = FunctionBodyDriftDetector().compare(declared, live_routines(conn, ["public"]))

    assert report.has_drift
    drift = report.body_drifts[0]
    assert drift.signature_key == "public.calc_total(numeric)"

    # The raw live body comes straight from pg_proc.prosrc.
    assert "1.196" in drift.live_body
    assert "1.20" in drift.expected_body

    # The unified diff is line-oriented, comment-stripped, and pinpoints the change.
    assert "-return amount * 1.20;" in drift.unified_diff
    assert "+return amount * 1.196;" in drift.unified_diff
    # The unchanged BEGIN/END scaffold is not reported as +/- churn, and the
    # "-- Apply 20% VAT" comment is normalised away rather than shown as drift.
    assert "20% vat" not in drift.unified_diff.lower()
