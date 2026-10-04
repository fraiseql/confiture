"""A savepoint name confiture executes is an identifier, quoted as one (#599).

They were interpolated into f-strings bare: a name with a capital was folded, and
one with a hyphen or a dot was a syntax error in the middle of a seed run.
"""

from pathlib import Path

import psycopg
import pytest

from confiture.core.seed.executor import SeedExecutor

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("name", ["Seed_01", "seed-01.users", "select"])
def test_a_seed_file_runs_under_any_savepoint_name(
    test_db_connection: psycopg.Connection, name: str
) -> None:
    executor = SeedExecutor(connection=test_db_connection)

    executor.execute_sql(
        "CREATE TEMP TABLE t_savepoint_name (id int)", name, source=Path("seed.sql")
    )

    with test_db_connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('pg_temp.t_savepoint_name') IS NOT NULL")
        assert cursor.fetchone() == (True,)
    test_db_connection.rollback()
