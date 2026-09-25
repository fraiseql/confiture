"""Two spellings of one column type are one type, and a real change still reports.

`confiture drift` compared an expected type against a live one through
``_types_compatible``, an 11-entry dict of aliases with no notion of typmods,
arrays, domains or the parser's qualifier. It was the thirteenth alias table in
the package, and the one the one-canonicaliser guard allow-listed with a reason.

Now both sides go through ``type_lattice.same_type``, which is the one
canonicaliser plus the rule the inventory already applies to a routine's
arguments: *a schema written on one side and left off the other matches*, because
PostgreSQL resolves the bare spelling through ``search_path`` and lands on the
same type.

Every row is a pair the drift comparison actually sees: the left column is what
``inventory._sql_type`` renders from the DDL, the right what
``format_type(atttypid, atttypmod)`` returns from the database.
"""

from __future__ import annotations

import pytest

from confiture.core.type_lattice import same_type

#: ``(expected as the DDL wrote it, actual as PostgreSQL stores it)``.
ONE_TYPE = [
    ("bigserial", "bigint"),
    ("serial", "integer"),
    ("varchar(50)", "character varying(50)"),
    ("text[]", "text[]"),
    ("integer[]", "integer[]"),
    ("json", "json"),
    ("bit(3)", "bit(3)"),
    ("bit varying(8)", "bit varying(8)"),
    ("varbit(8)", "bit varying(8)"),
    ("numeric(10, 2)", "numeric(10,2)"),
    ("numeric(10, 2)[]", "numeric(10,2)[]"),
    ("char(4)", "character(4)"),
    ("char", "character(1)"),
    ("timestamptz", "timestamp with time zone"),
    ("timestamp(3)", "timestamp(3) without time zone"),
    ("time(3)", "time(3) without time zone"),
    # A domain and an enum: `format_type` qualifies them, and so does the DDL.
    ("core.pos", "core.pos"),
    ("core.mood", "core.mood"),
    # The schema wildcard: `format_type` omits a schema that is visible through
    # `search_path`, so a qualified DDL spelling meets a bare live one.
    ("public.citext", "citext"),
    ("citext", "public.citext"),
]

#: Pairs that must still report, or the fold above is a shrug.
TWO_TYPES = [
    ("integer", "bigint"),
    ("integer[]", "integer"),
    ("text", "text[]"),
    ("varchar(50)", "character varying(100)"),
    ("timestamp", "timestamp with time zone"),
    ("numeric(10,2)", "numeric(12,2)"),
    ("char(4)", "character(1)"),
    ("bit(3)", "bit varying(3)"),
    # Two schemas that both say something, and disagree: two types.
    ("app.custom_t", "other.custom_t"),
]


@pytest.mark.parametrize(("expected", "actual"), ONE_TYPE)
def test_one_type_does_not_report(expected: str, actual: str) -> None:
    assert same_type(expected, actual), f"{expected!r} vs {actual!r}"


@pytest.mark.parametrize(("expected", "actual"), TWO_TYPES)
def test_two_types_report(expected: str, actual: str) -> None:
    assert not same_type(expected, actual), f"{expected!r} vs {actual!r}"


def test_a_missing_side_is_not_a_match() -> None:
    """Nothing is known about a column with no type on one side, so nothing is claimed."""
    assert not same_type(None, "bigint")
    assert not same_type("bigint", None)
    assert not same_type(None, None)


def test_the_predicate_is_symmetric() -> None:
    for expected, actual in (*ONE_TYPE, *TWO_TYPES):
        assert same_type(expected, actual) == same_type(actual, expected), (expected, actual)
