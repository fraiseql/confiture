"""Level 1 reads a seed file of many statements in time linear in the file.

Reading each statement's rows walked the file's whole token list to find the
statement's own, and a row's line counted the newlines from the top of the file,
so a file of n single-row ``INSERT`` statements cost O(n × file). Measured on
3000 statements, before and after: 5466 ms -> 211 ms. ``sql_lexer.parse``
counted from the top for every statement too, and now counts on from the last.

The bound is absolute and roughly twentyfold, as in ``test_lexer_scaling``.
"""

from __future__ import annotations

import time

import pytest

from confiture.core.seed.validation.prep_seed.seed_rows import read_seed_statements

pytestmark = pytest.mark.benchmark

_STATEMENTS = 5000
_OK = "550e8400-e29b-41d4-a716-446655440000"


def test_a_seed_file_of_many_inserts_reads_promptly() -> None:
    sql = "\n".join(
        f"INSERT INTO prep_seed.tb_x (id, name) VALUES ('{_OK}', 'n{i}');"
        for i in range(_STATEMENTS)
    )
    started = time.perf_counter()
    read = read_seed_statements(sql)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert len(read.writes) == _STATEMENTS
    assert read.writes[-1].rows[0].line == _STATEMENTS
    print(f"\n{_STATEMENTS} statements, {len(sql) / 1e6:.2f} MB: {elapsed_ms:.1f} ms")
    assert elapsed_ms < 8000, elapsed_ms
