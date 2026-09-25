"""COPY's CSV format, read as PostgreSQL reads it (``CopyReadAttributesCSV``) (#397).

A field is split on the delimiter outside quotes; inside quotes the delimiter and a
newline are data, and the escape character (the quote by default) before a quote or
itself is that character. An unquoted field equal to the NULL string (empty by
default) is NULL, a quoted one never is — unless its column is ``FORCE_NULL`` — and a
``FORCE_NOT_NULL`` column is never NULL. A row ends at a newline outside quotes, so a
row is not a line.
"""

from __future__ import annotations

import random

import pytest

from confiture.core.seed.copy_formatter import CsvOptions, copy_csv_rows


def _values(data: str, **options: object) -> list[tuple]:
    return [values for _, values in copy_csv_rows(data, CsvOptions(**options))]


def test_a_row_splits_on_commas_outside_quotes() -> None:
    assert _values('a,"b,c",d\n') == [("a", "b,c", "d")]


def test_a_doubled_quote_inside_quotes_is_one_quote() -> None:
    assert _values('"say ""hi""",x\n') == [('say "hi"', "x")]


def test_an_escape_other_than_the_quote_escapes_the_quote_and_itself() -> None:
    assert _values('"a\\"b\\\\c",x\n', escape="\\") == [('a"b\\c', "x")]


def test_an_unquoted_empty_field_is_null_and_a_quoted_one_is_not() -> None:
    assert _values(',"",x\n') == [(None, "", "x")]


def test_the_null_string_is_null_only_unquoted() -> None:
    assert _values('NULL,"NULL"\n', null="NULL") == [(None, "NULL")]


def test_force_null_makes_a_quoted_null_string_null() -> None:
    assert _values('"",""\n', force_null=frozenset({1})) == [("", None)]


def test_force_not_null_keeps_an_unquoted_empty_field() -> None:
    assert _values(",\n", force_not_null=frozenset({0})) == [("", None)]


def test_a_quoted_field_may_span_lines_and_the_next_row_starts_after_it() -> None:
    rows = copy_csv_rows('1,"two\nlines"\n2,x\n')
    assert rows == [(0, ("1", "two\nlines")), (2, ("2", "x"))]


def test_a_crlf_ending_is_the_row_ending() -> None:
    assert _values("a,b\r\nc,d\r\n") == [("a", "b"), ("c", "d")]


def test_a_header_is_skipped() -> None:
    assert copy_csv_rows("id,slug\n1,x\n", CsvOptions(header=True)) == [(1, ("1", "x"))]


def test_a_header_that_must_match_the_column_list_is_checked() -> None:
    assert _values("id,slug\n1,x\n", header="match", columns=("id", "slug")) == [("1", "x")]
    with pytest.raises(ValueError, match="header"):
        copy_csv_rows("id,name\n1,x\n", CsvOptions(header="match", columns=("id", "slug")))


def test_an_unterminated_quote_is_refused() -> None:
    with pytest.raises(ValueError, match="unterminated"):
        copy_csv_rows('a,"b\n')


def test_a_delimiter_and_quote_of_ones_choosing() -> None:
    assert _values("a;'b;c'\n", delimiter=";", quote="'") == [("a", "b;c")]


#: Every character CSV treats specially, and some it does not.
ALPHABET = 'ab ,"\n\r\\;x\té'


def _pg_csv_field(value: str | None) -> str:
    """A field as PostgreSQL's ``COPY … TO`` writes it: quoted where it must be."""
    if value is None:
        return ""
    if value == "" or any(c in value for c in ',"\n\r'):
        return '"' + value.replace('"', '""') + '"'
    return value


def test_every_row_round_trips_through_postgresqls_quoting() -> None:
    rng = random.Random(397)

    def value() -> str | None:
        if rng.random() < 0.15:
            return None
        return "".join(rng.choice(ALPHABET) for _ in range(rng.randrange(8)))

    rows = [tuple(value() for _ in range(3)) for _ in range(500)]
    data = "".join(",".join(_pg_csv_field(v) for v in row) + "\n" for row in rows)
    assert _values(data) == rows
