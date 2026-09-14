r"""``_lex`` reads the file once, however many ``COPY … FROM stdin`` blocks are in it.

Issue #278, and it was two quadratics, not one:

- **The rescan.** When the scanner errors inside a block's data, ``_lex`` cannot
  resume the original token list across it and rescans — and ``pglast.parser.scan``
  reads its whole buffer however early the error is, so each block cost O(remaining)
  and n blocks O(n × total). What makes the scanner error is an apostrophe in a text
  value, which is every real dump; ``\.`` itself scans quite happily.
- **The index searches.** Finding where a block's data starts, and where the token
  list picks up after it, both walked the token list from index 0 for every block.
  That one bites even when the data lexes cleanly and no rescan ever happens.

Measured here at 1600 blocks, before and after:

    quoted data   38003.9 ms -> 188.5 ms
    clean data     3906.4 ms ->  79.1 ms

Both shapes are timed because each covers a different half. The bounds are absolute
and roughly twentyfold — a ratio between two small measurements is a ratio between
two tails as much as between two costs, and this leg runs unattended. The
deterministic half of the guard, on how much text is handed to the scanner, is a
unit test: ``TestTheTextIsScannedOnce`` in ``tests/unit/test_sql_lexer_copy_blocks``.
"""

from __future__ import annotations

import time

import pytest

from confiture.core.sql_lexer import _lex, blank_copy_blocks

pytestmark = pytest.mark.benchmark

_BLOCKS = 1600
_REPEATS = 3


def _seed_sql(blocks: int, *, quoted: bool, rows: int = 3) -> str:
    """A pg_dump-shaped file: one table and one ``COPY`` block per table."""
    value = "O'Brien" if quoted else "plain"
    parts = []
    for i in range(blocks):
        parts.append(f"CREATE TABLE t{i} (a int, b text);\n")
        parts.append(f"COPY t{i} (a, b) FROM stdin;\n")
        parts.extend(f"{r}\t{value}-{r}\n" for r in range(rows))
        parts.append("\\.\n")
    return "".join(parts)


def _floor_ms(work) -> float:
    """The fastest of ``_REPEATS`` runs — the cost, with less of the machine in it."""
    return min(_timed(work) for _ in range(_REPEATS))


def _timed(work) -> float:
    started = time.perf_counter()
    work()
    return (time.perf_counter() - started) * 1000


@pytest.mark.parametrize(
    ("quoted", "ceiling_ms"),
    [
        # 38.0 s before the fix: the scanner errors in the data, so every block
        # rescanned the rest of the file.
        pytest.param(True, 4000, id="quoted-data-rescans"),
        # 3.9 s before the fix: nothing rescans, and the index searches alone were
        # enough to make it quadratic.
        pytest.param(False, 2000, id="clean-data-resumes"),
    ],
)
def test_a_pg_dump_shaped_seed_file_lexes_promptly(quoted: bool, ceiling_ms: int) -> None:
    sql = _seed_sql(_BLOCKS, quoted=quoted)
    assert len(_lex(sql)[1]) == _BLOCKS, "the corpus must actually hold the blocks it claims"
    elapsed_ms = _floor_ms(lambda: _lex(sql))
    print(f"\n{_BLOCKS} blocks, {len(sql) / 1e6:.2f} MB, quoted={quoted}: {elapsed_ms:.1f} ms")
    assert elapsed_ms < ceiling_ms, elapsed_ms


def test_blanking_a_seed_file_is_prompt_too() -> None:
    """The public entry point #274 put on ``confiture lint``'s default path."""
    sql = _seed_sql(_BLOCKS, quoted=True)
    assert "O'Brien" not in blank_copy_blocks(sql)
    elapsed_ms = _floor_ms(lambda: blank_copy_blocks(sql))
    print(f"\nblank {_BLOCKS} blocks: {elapsed_ms:.1f} ms")
    assert elapsed_ms < 4000, elapsed_ms
