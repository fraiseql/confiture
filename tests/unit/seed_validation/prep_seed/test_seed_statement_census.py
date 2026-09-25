"""Every seed statement is read by level 1, or named with the reason it is not.

The corpus is every tracked seed file in the repository — the examples' and
``tests/fixtures/seed_shapes/``, one file per statement shape — and ``READS`` pins
what level 1 makes of each shape. A statement of a kind level 1 neither reads nor
names in ``UNREAD_SEED_STATEMENTS`` fails here, and so does a reason in that table
no statement in the corpus needs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pglast
import pytest

from confiture.core import sql_lexer
from confiture.core.seed.validation.prep_seed.seed_rows import (
    UNREAD_SEED_STATEMENTS,
    SeedParseError,
    read_seed_statements,
)

REPO = Path(__file__).resolve().parents[4]
SHAPES = "tests/fixtures/seed_shapes/"

#: The statement kinds level 1 reads rows from.
READ_KINDS = frozenset({"InsertStmt", "CopyStmt"})

#: Kinds level 1 reports as not checked (an INFO finding), each pinned by a shape.
REPORTED_KINDS = frozenset({"UpdateStmt"})

#: Per shape: (rows read, statements reported as not checked); ``None`` when the
#: parser rejects the file.
READS: dict[str, tuple[int, int] | None] = {
    "copy_csv.sql": (0, 1),
    "copy_from_file.sql": (0, 1),
    "copy_text.sql": (2, 0),
    "insert_default_values.sql": (0, 1),
    "insert_select.sql": (0, 1),
    "insert_values.sql": (2, 0),
    "session_statements.sql": (0, 0),
    "unparseable.sql": None,
    "update.sql": (0, 1),
}


def _seed_files() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "*.sql"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    return [f for f in listed if "/seeds/" in f or "seed_" in Path(f).name or f.startswith(SHAPES)]


def _kinds(text: str) -> list[str]:
    kinds = [type(p.stmt).__name__ for p in sql_lexer.parse(sql_lexer.blank_copy_blocks(text))]
    return kinds + ["CopyStmt"] * len(sql_lexer.copy_blocks(text))


def test_the_corpus_holds_every_shape() -> None:
    shapes = {Path(f).name for f in _seed_files() if f.startswith(SHAPES)}
    assert shapes == set(READS)


@pytest.mark.parametrize("shape", sorted(READS))
def test_each_shape_reads_as_pinned(shape: str) -> None:
    text = (REPO / SHAPES / shape).read_text(encoding="utf-8")
    expected = READS[shape]
    if expected is None:
        with pytest.raises(SeedParseError):
            read_seed_statements(text)
        return
    read = read_seed_statements(text)
    assert (sum(len(w.rows) for w in read.writes), len(read.unread)) == expected


def test_every_statement_is_read_or_named() -> None:
    seen: set[str] = set()
    for name in _seed_files():
        text = (REPO / name).read_text(encoding="utf-8")
        try:
            seen.update(_kinds(text))
        except pglast.parser.ParseError:
            continue  # the unparseable shape, pinned above
    unnamed = seen - READ_KINDS - REPORTED_KINDS - set(UNREAD_SEED_STATEMENTS)
    assert unnamed == set(), f"statement kinds level 1 neither reads nor names: {unnamed}"
    idle = (REPORTED_KINDS | set(UNREAD_SEED_STATEMENTS)) - seen
    assert idle == set(), f"entries no seed statement in the corpus needs: {idle}"
