"""Latency of the SQL guards on a large DO-block file, and the package import time.

The guards that run on every migration file — statement splitting, the psql
meta-command scan and the non-transactional analyzer — must stay cheap on a 50 KB
file full of dollar-quoted ``DO`` blocks (the shape that defeated the regex
splitters). ``import confiture`` must stay lazy. The bounds are loose enough for a
slow CI runner; the measured numbers are printed so a regression shows in the log
before it trips the bound.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from confiture.core.migration_analyzer import MigrationAnalyzer
from confiture.core.psql_applier import find_meta_commands
from confiture.core.sql_lexer import split_statements

pytestmark = pytest.mark.benchmark

BLOCK = """DO $body$
DECLARE
    v_count integer;
BEGIN
    SELECT count(*) INTO v_count FROM pg_class WHERE relname = 'widget_{n}';
    IF v_count = 0 THEN
        EXECUTE 'CREATE TABLE widget_{n} (id serial PRIMARY KEY, note text DEFAULT ''a;b'')';
    END IF;
    RAISE NOTICE 'checked widget_{n}; semicolons; inside; strings';
END
$body$;
"""


def _fifty_kb_of_do_blocks() -> str:
    blocks = []
    n = 0
    while sum(len(b) for b in blocks) < 50_000:
        blocks.append(BLOCK.format(n=n))
        n += 1
    return "".join(blocks)


def _timed(label: str, fn, *args) -> float:
    start = time.perf_counter()
    fn(*args)
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(f"{label}: {elapsed_ms:.1f} ms")
    return elapsed_ms


def test_do_block_guards_stay_fast_on_fifty_kb() -> None:
    sql = _fifty_kb_of_do_blocks()
    assert len(sql) >= 50_000
    split_ms = _timed("split_statements", split_statements, sql)
    meta_ms = _timed("find_meta_commands", find_meta_commands, sql)
    analyze_ms = _timed("MigrationAnalyzer.analyze", MigrationAnalyzer().analyze, sql)
    assert split_ms < 1000, "statement splitting is no longer linear"
    assert meta_ms < 1000, "the meta-command scan is no longer linear"
    assert analyze_ms < 2000, "the non-transactional analyzer is no longer linear"


def test_import_confiture_stays_lazy() -> None:
    start = time.perf_counter()
    subprocess.run([sys.executable, "-c", "import confiture"], check=True)
    baseline = time.perf_counter()
    subprocess.run([sys.executable, "-c", "pass"], check=True)
    end = time.perf_counter()
    import_ms = (baseline - start) * 1000 - (end - baseline) * 1000
    print(f"import confiture (net of interpreter start-up): {import_ms:.1f} ms")
    assert import_ms < 300, "import confiture pulls in too much at import time"
