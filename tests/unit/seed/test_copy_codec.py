"""COPY's text format has one codec: ``copy_escape`` writes a field, ``copy_row`` reads a line.

The reader is PostgreSQL's own reading of a text-format row (``CopyReadAttributesText``):
fields split on the delimiter, a field that is exactly the NULL marker is NULL, and
backslash escapes — the six letters, up to three octal digits, ``\\x`` and up to two
hex digits, anything else the character itself — are decoded, as bytes in the
file's encoding.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from confiture import platform
from confiture.core.seed.copy_formatter import copy_escape, copy_row, copy_unescape
from confiture.core.sql_lexer import copy_blocks

#: Every character COPY's text format treats specially, some it does not, and text
#: that is more than one byte in UTF-8.
ALPHABET = "ab \\\t\n\r\b\f\x0bN.x0719é€😀'\""


@pytest.mark.parametrize(
    ("field", "text"),
    [
        ("plain", "plain"),
        ("a\\tb", "a\tb"),
        ("a\\nb\\rc", "a\nb\rc"),
        ("\\b\\f\\v", "\b\f\x0b"),
        ("back\\\\slash", "back\\slash"),
        ("\\101\\1011", "AA1"),
        ("\\x41\\x4g", "A\x04g"),
        ("\\xc3\\xa9", "é"),
        ("\\q\\.", "q."),
        ("\\N-inside", "N-inside"),
    ],
)
def test_a_field_decodes_as_postgresql_reads_it(field: str, text: str) -> None:
    assert copy_unescape(field) == text


def test_the_null_marker_is_null_only_as_a_whole_field() -> None:
    assert copy_row("\\N\t\\\\N\tx\\N") == (None, "\\N", "xN")


def test_a_row_splits_on_its_delimiter_and_ignores_a_carriage_return_ending() -> None:
    assert copy_row("a\tb\t\r") == ("a", "b", "")
    assert copy_row("a|b\\|c", delimiter="|") == ("a", "b|c")
    assert copy_row("a\tNULL", null="NULL") == ("a", None)


def test_bytes_that_are_not_utf8_are_refused() -> None:
    with pytest.raises(ValueError, match="UTF-8"):
        copy_unescape("\\xff")


def test_every_text_round_trips_through_the_codec() -> None:
    rng = random.Random(366)
    for _ in range(2000):
        text = "".join(rng.choice(ALPHABET) for _ in range(rng.randrange(12)))
        assert copy_unescape(copy_escape(text)) == text


def test_every_row_write_copy_seed_writes_decodes_to_the_row_it_was_given(
    tmp_path: Path,
) -> None:
    model = platform.parse_schema("CREATE TABLE app.t (a TEXT, b TEXT, c TEXT);")
    rng = random.Random(387)

    def value() -> str | None:
        if rng.random() < 0.1:
            return None
        return "".join(rng.choice(ALPHABET) for _ in range(rng.randrange(10)))

    rows = [{"a": value(), "b": value(), "c": value()} for _ in range(300)]
    path = tmp_path / "t.sql"
    platform.write_copy_seed(path, "app.t", ["a", "b", "c"], rows, model=model)

    (block,) = copy_blocks(path.read_text(encoding="utf-8"))
    decoded = [copy_row(line) for line in block.data.split("\n")[:-1]]
    assert decoded == [(r["a"], r["b"], r["c"]) for r in rows]
