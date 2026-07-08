"""Integration test for issue #176 — array-typed function signatures.

An array-typed function present identically in the source DDL and the live
database must NOT be reported as a stale overload, and must never produce a
destructive ``DROP FUNCTION`` remediation.  This exercises the real
``pg_catalog.format_type`` output from a live server (``text[]``, ``bigint[]``,
…), which is the symmetry the parser fix must preserve.

Requires a running PostgreSQL server accessible via CONFITURE_TEST_DB_URL.
"""

from __future__ import annotations

import psycopg
import pytest

from confiture.core.function_signature_drift import FunctionSignatureDriftDetector
from confiture.core.function_signature_parser import FunctionSignatureParser
from confiture.core.live_function_catalog import LiveFunctionCatalog

# The pglast AST path is the production path and the one that dropped '[]'.
pytest.importorskip("pglast")

_DDL = """
CREATE SCHEMA IF NOT EXISTS sig176;

CREATE FUNCTION sig176.merge_to_tenant_statistics(
    p_tenant text,
    p_dates date[],
    p_ids bigint[],
    p_uuids uuid[]
) RETURNS void LANGUAGE plpgsql AS $$ BEGIN END $$;

CREATE FUNCTION sig176.build_response(
    a text,
    tags text[] DEFAULT ARRAY[]::text[]
) RETURNS void LANGUAGE plpgsql AS $$ BEGIN END $$;
"""


@pytest.fixture
def array_fn_db(clean_test_db: psycopg.Connection) -> psycopg.Connection:
    conn = clean_test_db
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS sig176 CASCADE")
        cur.execute(_DDL)
    conn.commit()
    yield conn
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS sig176 CASCADE")
    conn.commit()


def test_array_functions_not_stale_against_live_db(array_fn_db: psycopg.Connection) -> None:
    source_sigs = FunctionSignatureParser().parse(_DDL)
    live_sigs = LiveFunctionCatalog(array_fn_db).get_signatures(schemas=["sig176"])

    report = FunctionSignatureDriftDetector().compare(
        source_sigs, live_sigs, schemas_checked=["sig176"]
    )

    # No false stale overload, and — critically — no destructive DROP emitted.
    assert not report.has_drift, report.to_dict()["stale_overloads"]
    assert report.to_dict()["remediation_sql"] == []


def test_live_array_signature_matches_source(array_fn_db: psycopg.Connection) -> None:
    """The live introspected signature keeps its array suffix and equals source."""
    live_sigs = LiveFunctionCatalog(array_fn_db).get_signatures(schemas=["sig176"])
    keys = {s.signature_key() for s in live_sigs}

    assert "sig176.merge_to_tenant_statistics(text,date[],bigint[],uuid[])" in keys, keys
    assert "sig176.build_response(text,text[])" in keys, keys
