"""``copy_csv_rows`` reads a CSV ``COPY`` block as PostgreSQL loads it (#397).

Each case is loaded by the server (``COPY … FROM STDIN``) and decoded by
confiture, and the rows must be the same: PostgreSQL is the oracle.
"""

from __future__ import annotations

import random

import psycopg
import pytest

from confiture.core.seed.copy_formatter import CsvOptions, copy_csv_rows

#: (the block's data, the statement's options, the decoder's options)
CASES: list[tuple[str, str, CsvOptions]] = [
    ('a,"b,c",d\n', "", CsvOptions()),
    ('"say ""hi""",x,\n', "", CsvOptions()),
    (',"",x\n', "", CsvOptions()),
    ('1,"two\nlines",3\n2,x,y\n', "", CsvOptions()),
    ("a,b,c\r\nd,e,f\r\n", "", CsvOptions()),
    ('"a\\"b",\\\\,"c\\\\"\n', ", ESCAPE '\\'", CsvOptions(escape="\\")),
    ('NULL,"NULL",x\n', ", NULL 'NULL'", CsvOptions(null="NULL")),
    ('"",,""\n', ", FORCE_NULL (a, c)", CsvOptions(force_null=frozenset({0, 2}))),
    (",,x\n", ", FORCE_NOT_NULL (b)", CsvOptions(force_not_null=frozenset({1}))),
    ("a,b,c\n1,2,3\n", ", HEADER", CsvOptions(header=True)),
    ("a,b,c\n1,2,3\n", ", HEADER match", CsvOptions(header="match", columns=("a", "b", "c"))),
    ("x;'y;z';w\n", ", DELIMITER ';', QUOTE ''''", CsvOptions(delimiter=";", quote="'")),
]


def _loaded(conn: psycopg.Connection, data: str, options: str) -> list[tuple]:
    conn.execute("CREATE TEMP TABLE t (n int GENERATED ALWAYS AS IDENTITY, a text, b text, c text)")
    try:
        with conn.cursor().copy(f"COPY t (a, b, c) FROM STDIN (FORMAT csv{options})") as copy:
            copy.write(data)
        return list(conn.execute("SELECT a, b, c FROM t ORDER BY n"))
    finally:
        conn.execute("DROP TABLE t")


@pytest.mark.parametrize(("data", "options", "decoder"), CASES)
def test_the_rows_are_the_ones_postgresql_loads(
    test_db_connection: psycopg.Connection, data: str, options: str, decoder: CsvOptions
) -> None:
    decoded = [values for _, values in copy_csv_rows(data, decoder)]
    assert decoded == _loaded(test_db_connection, data, options)


def test_random_rows_are_the_ones_postgresql_loads(test_db_connection: psycopg.Connection) -> None:
    rng = random.Random(3970)
    alphabet = 'ab ,"\n\r\\x'

    def field() -> str:
        text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(6)))
        if rng.random() < 0.5 or any(c in text for c in ',"\n\r'):
            return '"' + text.replace('"', '""') + '"'
        return text

    data = "".join(",".join(field() for _ in range(3)) + "\n" for _ in range(300))
    decoded = [values for _, values in copy_csv_rows(data)]
    assert decoded == _loaded(test_db_connection, data, "")
