"""Integration tests for the COPY-aware ``psql`` applier (#159).

Requires a reachable local PostgreSQL (``CONFITURE_TEST_DB_URL`` or localhost)
and ``psql`` on PATH. Uses :class:`TempDatabase` for a throwaway database that is
dropped on exit.
"""

from __future__ import annotations

import os
import shutil

import psycopg
import pytest

from confiture.core.psql_applier import apply_sql_via_psql
from confiture.core.seed_applier import apply_seed_files
from confiture.core.temp_database import TempDatabase, _maintenance_url
from confiture.exceptions import SchemaError

pytestmark = pytest.mark.integration


def _server_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


@pytest.fixture
def temp_url():
    url = _server_url()
    if shutil.which("psql") is None:
        pytest.skip("psql not on PATH")
    try:
        with psycopg.connect(_maintenance_url(url), autocommit=True):
            pass
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")
    with TempDatabase(url) as tmp_url:
        yield tmp_url


_COPY_SCHEMA = (
    "CREATE TABLE color (id int PRIMARY KEY, name text);\n"
    "COPY color (id, name) FROM stdin;\n"
    "1\tred\n"
    "2\tgreen\n"
    "3\tblue\n"
    "\\.\n"
)


class TestApplyInlineCopy:
    def test_copy_bearing_schema_rows_land(self, temp_url: str) -> None:
        apply_sql_via_psql(temp_url, _COPY_SCHEMA)
        with psycopg.connect(temp_url, autocommit=True) as conn:
            count = conn.execute("SELECT count(*) FROM color").fetchone()[0]
        assert count == 3

    def test_syntax_error_raises_schema_error(self, temp_url: str) -> None:
        with pytest.raises(SchemaError, match="psql failed"):
            apply_sql_via_psql(temp_url, "CREATE TABLE oops (")


class TestApplySeedFilesCopy:
    def test_copy_bearing_seed_file_applies(self, temp_url: str, tmp_path) -> None:
        with psycopg.connect(temp_url, autocommit=True) as conn:
            conn.execute("CREATE TABLE fruit (id int PRIMARY KEY, name text);")

        seed = tmp_path / "01_fruit.sql"
        seed.write_text("COPY fruit (id, name) FROM stdin;\n1\tapple\n2\tpear\n\\.\n")

        applied = apply_seed_files(temp_url, [seed])
        assert applied == 1

        with psycopg.connect(temp_url, autocommit=True) as conn:
            count = conn.execute("SELECT count(*) FROM fruit").fetchone()[0]
        assert count == 2
