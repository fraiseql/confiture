"""Every PL/pgSQL fragment is read, or named with a reason (#363).

The fragment reader decides how to parse a fragment from the statement and slot
the compiler put it in (``plpgsql_fragments.SLOTS``). A slot the table does not
name, or text pglast rejects, is a finding and never a silence — and this file
is what keeps that from being a promise. It compiles every PL/pgSQL body in
this repository's own schema, examples and fixtures, and fails on a fragment
that was not parsed unless its shape is in ``UNREAD_FRAGMENT_SHAPES`` with a
reason. The next unread shape fails here instead of going quiet.

``SLOTS`` is pinned the other way too: one body writes every statement that
carries SQL, so each entry is a slot this libpg_query really fills and each
slot it fills is an entry. It runs on each pglast major in the matrix leg.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pglast.parser
import pytest

from confiture.core import sql_lexer
from confiture.core.plpgsql_fragments import SLOTS, Fragment, Mode, fragments
from confiture.core.plpgsql_parse import parse_body

REPO = Path(__file__).resolve().parents[2]
TREES = ("db", "examples", "tests/fixtures")

#: ``(node, slot)`` → why a fragment in it is not parsed. Empty: every fragment
#: in the census reads. An entry that matches nothing fails.
UNREAD_FRAGMENT_SHAPES: dict[tuple[str, str], str] = {}

#: One body with every statement that carries SQL, each once.
EVERY_SLOT = """CREATE FUNCTION app.every_slot(p int) RETURNS SETOF int LANGUAGE plpgsql AS $$
DECLARE
  v int := g();
  r record;
  a int[];
  m int[];
  c CURSOR (k int) FOR SELECT * FROM t1 WHERE id = k;
  c2 refcursor;
BEGIN
  v := core.x(p);
  SELECT count(*) INTO v FROM t2;
  PERFORM z();
  CALL pr();
  IF v > 0 THEN NULL; ELSIF v < 0 THEN NULL; END IF;
  CASE v WHEN 1 THEN NULL; ELSE NULL; END CASE;
  WHILE v < 3 LOOP EXIT WHEN q(); END LOOP;
  FOR i IN 1..m() BY 1 LOOP NULL; END LOOP;
  FOR r IN SELECT * FROM t4 LOOP NULL; END LOOP;
  FOR r IN c(5) LOOP NULL; END LOOP;
  FOR r IN EXECUTE 'SELECT 1' USING u1() LOOP NULL; END LOOP;
  FOREACH v IN ARRAY a LOOP NULL; END LOOP;
  EXECUTE 'z' INTO v USING u4();
  OPEN c2 FOR SELECT * FROM t5; CLOSE c2;
  OPEN c2 FOR EXECUTE 'x' USING u2(); CLOSE c2;
  OPEN c(6); FETCH ABSOLUTE ab() FROM c INTO v; CLOSE c;
  RAISE NOTICE 'x %', k(v) USING DETAIL = dd();
  ASSERT w(), 'msg';
  RETURN NEXT v + 1;
  RETURN QUERY SELECT 1;
  RETURN QUERY EXECUTE 'y' USING u3();
  RETURN;
END $$;"""

#: Slots the probe above cannot fill in the same body: a ``RETURN`` with a
#: value needs a function that returns one.
ELSEWHERE = {
    ("PLpgSQL_stmt_return", "expr"): (
        "CREATE FUNCTION app.r() RETURNS int LANGUAGE plpgsql AS $$ BEGIN RETURN f() + 1; END $$;"
    ),
}


def _tracked_sql() -> list[Path]:
    """The ``.sql`` files git tracks under :data:`TREES`.

    Tracked, not walked: ``db/schema_history/`` fills with snapshots the suite
    itself writes, and a census of what happens to be on disk would differ
    between a laptop and CI.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", *(f"{tree}/*.sql" for tree in TREES)],
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout.decode()
    return [REPO / rel for rel in sorted(filter(None, listed.split("\0")))]


def _bodies() -> list[tuple[str, str]]:
    """``(file, statement)`` for every statement in the trees that may carry PL/pgSQL."""
    found: list[tuple[str, str]] = []
    for path in _tracked_sql():
        text = sql_lexer.blank_copy_blocks(path.read_text(encoding="utf-8", errors="replace"))
        found.extend(
            (path.relative_to(REPO).as_posix(), statement)
            for statement in sql_lexer.split_statements(text)
            if "plpgsql" in statement.lower() or statement.lstrip()[:2].upper() == "DO"
        )
    return found


def _census() -> list[tuple[str, Fragment]]:
    read: list[tuple[str, Fragment]] = []
    for where, statement in _bodies():
        try:
            compiled = parse_body(statement)
        except (pglast.parser.ParseError, json.JSONDecodeError):
            continue
        read.extend((where, fragment) for fragment in fragments(compiled))
    return read


def test_the_census_reads_something() -> None:
    modes = {fragment.mode for _where, fragment in _census()}

    assert {Mode.STATEMENT, Mode.EXPRESSION, Mode.ASSIGNMENT} <= modes


def test_every_fragment_is_read_or_named() -> None:
    unread = [
        f"{where}:{fragment.line} {fragment.kind}.{fragment.slot}: {fragment.finding}"
        for where, fragment in _census()
        if fragment.finding and (fragment.kind, fragment.slot) not in UNREAD_FRAGMENT_SHAPES
    ]

    assert unread == []


def test_every_unread_shape_is_still_met() -> None:
    met = {(f.kind, f.slot) for _where, f in _census() if f.finding}

    assert sorted(set(UNREAD_FRAGMENT_SHAPES) - met) == []


def _slots_of(statement: str) -> list[Fragment]:
    return list(fragments(parse_body(statement)))


def test_every_slot_the_compiler_fills_has_a_reading() -> None:
    read = [f for statement in (EVERY_SLOT, *ELSEWHERE.values()) for f in _slots_of(statement)]

    assert [f"{f.kind}.{f.slot}: {f.finding}" for f in read if f.finding] == []


def test_every_reading_is_a_slot_the_compiler_fills() -> None:
    filled = {
        (f.kind, f.slot)
        for statement in (EVERY_SLOT, *ELSEWHERE.values())
        for f in _slots_of(statement)
    }

    assert sorted(set(SLOTS) - filled) == []


@pytest.mark.parametrize(("slot", "statement"), list(ELSEWHERE.items()))
def test_each_elsewhere_probe_fills_its_slot(slot: tuple[str, str], statement: str) -> None:
    assert slot in {(f.kind, f.slot) for f in _slots_of(statement)}
