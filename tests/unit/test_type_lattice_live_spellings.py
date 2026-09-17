"""``canonical_type`` folds the spellings a live PostgreSQL hands back.

The expected side of a drift comparison spells a column's type the way the DDL
wrote it; the live side spells it the way ``format_type(atttypid, atttypmod)``
does. Both go through the one canonicaliser, so every pair PostgreSQL considers
the same type has to come out the same string. Four classes did not:

======================  ==============================  ==========================
DDL                     ``format_type``                 why
======================  ==============================  ==========================
``timestamp(3)``        ``timestamp(3) without time zone``  the regex wanted the typmod last
``time(3)``             ``time(3) without time zone``       same shape
``varbit(8)``           ``bit varying(8)``                  no ``varbit`` alias
``char``                ``character(1)``                    ``char`` *is* ``char(1)``
======================  ==============================  ==========================

Every row below was measured against PostgreSQL 18.4, including the one that
says ``bpchar`` is **not** ``char(1)``: a bare ``bpchar`` comes back as
``bpchar``, while ``char`` and ``character`` come back as ``character(1)``. So
the implicit length belongs to the spelling the author used, not to the
canonical name.
"""

from __future__ import annotations

import pytest

from confiture.core.type_lattice import TypeChange, canonical_type, compare_types

#: ``(what the DDL wrote, what format_type returns)`` — one type, two spellings.
SAME_TYPE = [
    ("timestamp(3)", "timestamp(3) without time zone"),
    ("timestamp", "timestamp without time zone"),
    ("timestamptz", "timestamp with time zone"),
    ("timestamptz(3)", "timestamp(3) with time zone"),
    ("time(3)", "time(3) without time zone"),
    ("timetz", "time with time zone"),
    ("varbit(8)", "bit varying(8)"),
    ("varbit", "bit varying"),
    ("char", "character(1)"),
    ("character", "character(1)"),
    ("char(4)", "character(4)"),
    ("varchar(50)", "character varying(50)"),
    ("varchar", "character varying"),
    ("int4", "integer"),
    ("bigserial", "bigint"),
    ("serial", "integer"),
    ("numeric(10, 2)", "numeric(10,2)"),
    ("numeric(10, 2)[]", "numeric(10,2)[]"),
    ("double", "double precision"),
    ("float8", "double precision"),
    ("bool", "boolean"),
    ("text[]", "text[]"),
    ("bit(3)", "bit(3)"),
    # `bpchar` with no length is its own type: measured, PostgreSQL renders it
    # `bpchar` and not `character(1)`.
    ("bpchar", "bpchar"),
]

#: Pairs that must stay apart, so the fold above did not become a shrug.
DIFFERENT_TYPES = [
    ("integer", "bigint"),
    ("integer[]", "integer"),
    ("text", "text[]"),
    ("timestamp", "timestamptz"),
    ("varchar(50)", "varchar(100)"),
    ("char", "char(4)"),
    ("numeric(10,2)", "numeric(12,2)"),
    ("bit(3)", "bit varying(3)"),
]


@pytest.mark.parametrize(("written", "live"), SAME_TYPE)
def test_one_type_canonicalises_to_one_string(written: str, live: str) -> None:
    assert canonical_type(written) == canonical_type(live)


@pytest.mark.parametrize(("written", "live"), DIFFERENT_TYPES)
def test_two_types_stay_two(written: str, live: str) -> None:
    assert canonical_type(written) != canonical_type(live)


def test_a_bare_char_is_char_of_one() -> None:
    """PostgreSQL's own default, so ``char`` and ``char(1)`` compare identical."""
    assert canonical_type("char") == "char(1)"
    assert compare_types("char", "char(1)") is TypeChange.IDENTICAL
    assert compare_types("char", "char(4)") is TypeChange.WIDENING


def test_a_parameterised_temporal_keeps_its_precision() -> None:
    assert canonical_type("timestamp(3) without time zone") == "timestamp(3)"
    assert canonical_type("time(3) with time zone") == "timetz(3)"
