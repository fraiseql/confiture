"""Integration test: function body drift + unified diff against real prosrc.

Reproduces the epic's core scenario — a function hot-patched directly in the
database (``CREATE OR REPLACE`` on prod) while the committed source SQL still
carries the old body — and asserts that the detector surfaces both bodies and a
readable, line-oriented unified diff built from the live ``pg_proc.prosrc``.

Requires a PostgreSQL server at ``CONFITURE_TEST_DB_URL``
(default ``postgresql://localhost/confiture_test``).
"""

from __future__ import annotations

import psycopg
import pytest

from confiture.core.function_body_drift import FunctionBodyDriftDetector
from confiture.core.function_signature_parser import FunctionSignatureParser
from confiture.core.live_function_catalog import LiveFunctionCatalog

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

    # Source side: parse the committed DDL into signature → body.
    source_bodies = {
        sig.signature_key(): body
        for sig, body in FunctionSignatureParser().parse_with_bodies(_SOURCE_SQL)
    }
    assert "public.calc_total(numeric)" in source_bodies

    # Live side: read the real prosrc back out of the database.
    live_bodies = LiveFunctionCatalog(conn).get_bodies(
        schemas=["public"], sig_keys=set(source_bodies)
    )

    report = FunctionBodyDriftDetector().compare(source_bodies, live_bodies)

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
