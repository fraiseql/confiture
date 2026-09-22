"""A seed script as ``psql`` reads one: statements, COPY rows, and what controls a transaction.

``copy_blocks`` hands a driver what ``psql`` would stream; ``transaction_statements``
answers "does this file open or end a transaction" by statement, not by word. Both
read pglast's scanner, whose token names this file pins on every supported major
(it runs in the ``pglast-matrix`` leg).
"""

from __future__ import annotations

import pytest

from confiture.core.sql_lexer import copy_blocks, transaction_statements


def test_a_block_is_its_statement_and_its_rows() -> None:
    sql = "-- load\nCOPY t (a, b) FROM stdin; -- inline\n1\tx\n2\t\\N\n\\.\nSELECT 1;\n"
    (block,) = copy_blocks(sql)
    assert block.statement == "COPY t (a, b) FROM stdin; -- inline"
    assert block.data == "1\tx\n2\t\\N\n"
    assert sql[block.start :].startswith("COPY")
    assert sql[block.end :] == "SELECT 1;\n"


def test_rows_that_the_scanner_rejects_are_still_rows() -> None:
    """``28df`` is junk after a numeric literal to the scanner, and data to COPY."""
    sql = "COPY t (id) FROM stdin;\nb2b9437a-28df-4ec4\n\\.\nCOPY u FROM stdin;\n'\n\\.\n"
    assert [(b.statement, b.data) for b in copy_blocks(sql)] == [
        ("COPY t (id) FROM stdin;", "b2b9437a-28df-4ec4\n"),
        ("COPY u FROM stdin;", "'\n"),
    ]


def test_a_block_with_no_rows_or_no_terminator() -> None:
    assert copy_blocks("COPY t FROM stdin;\n\\.\n")[0].data == ""
    assert copy_blocks("COPY t FROM stdin;\n1\n2")[0].data == "1\n2"
    assert copy_blocks("COPY t FROM stdin;\r\n1\r\n\\.\r\n")[0].data == "1\r\n"


def test_copy_to_stdout_and_from_a_file_are_not_blocks() -> None:
    assert copy_blocks("COPY t TO stdout;\nCOPY t FROM '/tmp/x';\n") == []


@pytest.mark.parametrize(
    ("sql", "count"),
    [
        ("BEGIN;\nINSERT INTO t VALUES (1);\nCOMMIT;", 2),
        ("/* c */ begin work; end;", 2),
        ("START TRANSACTION; SAVEPOINT a; RELEASE a; ROLLBACK TO a; ABORT;", 5),
        ("PREPARE TRANSACTION 'x';", 1),
        ("PREPARE p AS SELECT 1; EXECUTE p;", 0),
        ("INSERT INTO t VALUES ('Begin here; then COMMIT.');", 0),
        ("DO $$ BEGIN PERFORM 1; END $$;", 0),
        ("SELECT CASE WHEN true THEN 1 END;", 0),
        ("COPY t FROM stdin;\nBEGIN\nCOMMIT\n\\.\n", 0),
        ("-- COMMIT\nSELECT 1;", 0),
    ],
    ids=[
        "begin-commit",
        "lower-case-and-comment",
        "start-savepoint-release-rollback-abort",
        "prepare-transaction",
        "prepare-statement",
        "word-in-a-string",
        "do-body",
        "case-end",
        "copy-rows",
        "comment",
    ],
)
def test_transaction_control_is_a_statement(sql: str, count: int) -> None:
    assert transaction_statements(sql) == count
