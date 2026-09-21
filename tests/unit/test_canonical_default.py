"""``ddl_walk.canonical_default``: one default, whichever side wrote it.

A default reaches drift twice — as the DDL wrote it and as ``pg_get_expr`` gives it
back — and PostgreSQL stores it analysed: ``'x'`` in a ``text`` column comes back
``'x'::text``, ``1 + 2`` comes back ``(1 + 2)``, ``TRUE`` comes back ``true``.
Compared as text, 10 of 23 shapes agreed; read as a parse tree, all 23 do. What is
measured against a real server is ``tests/integration/test_default_comparison_is_measured.py``;
this is the rule, one row per rewrite.
"""

from __future__ import annotations

import pglast
import pytest

from confiture.core.ddl_walk import canonical_default

#: ``(column type, as the DDL writes it, as the catalog gives it back)``.
SAME = [
    ("text", "'x'", "'x'::text"),
    ("text[]", "'{}'", "'{}'::text[]"),
    ("varchar(10)", "'ab'", "'ab'::character varying"),
    ("character varying(20)", "'active'::character varying", "'active'::character varying"),
    ("boolean", "TRUE", "true"),
    ("integer", "1 + 2", "(1 + 2)"),
    ("jsonb", "CAST('{}' AS jsonb)", "'{}'::jsonb"),
    ("integer", "-7", "'-7'::integer"),
    ("numeric(10,2)", "1.50", "1.50"),
    ("date", "'2020-01-01'", "'2020-01-01'::date"),
    ("text", "'it''s'", "'it''s'::text"),
    ("integer[]", "ARRAY[1,2]", "ARRAY[1, 2]"),
    ("text", "lower('ABC')", "lower('ABC'::text)"),
    ("interval", "'1 day'", "'1 day'::interval"),
    ("timestamptz", "CURRENT_TIMESTAMP", "CURRENT_TIMESTAMP"),
]


@pytest.mark.parametrize(("column_type", "written", "stored"), SAME)
def test_a_default_and_its_stored_form_are_one_default(
    column_type: str, written: str, stored: str
) -> None:
    assert canonical_default(written, column_type) == canonical_default(stored, column_type)


@pytest.mark.parametrize(
    ("column_type", "one", "other"),
    [
        ("text", "'x'", "'y'::text"),
        ("integer", "0", "1"),
        ("boolean", "true", "false"),
        ("timestamptz", "now()", "CURRENT_TIMESTAMP"),
        ("text", "lower('ABC')", "upper('ABC'::text)"),
    ],
)
def test_two_defaults_that_differ_stay_different(column_type: str, one: str, other: str) -> None:
    assert canonical_default(one, column_type) != canonical_default(other, column_type)


def test_no_default_is_none() -> None:
    assert canonical_default(None, "text") is None


def test_null_is_no_default() -> None:
    """PostgreSQL stores no default for ``DEFAULT NULL``, so the two are one."""
    assert canonical_default("NULL", "text") is None
    assert canonical_default("NULL::text", "text") is None


def test_an_outer_cast_to_the_columns_own_type_is_dropped() -> None:
    assert canonical_default("(next_id())::integer", "integer") == canonical_default(
        "next_id()", "integer"
    )


def test_a_cast_to_another_type_is_kept() -> None:
    """Only the analyser's cast to the column's type is noise; any other one says something."""
    assert canonical_default("(next_id())::bigint", "integer") != canonical_default(
        "next_id()", "integer"
    )


def test_without_a_column_type_only_the_literal_casts_go() -> None:
    assert canonical_default("lower('ABC'::text)", None) == "lower('ABC')"
    assert canonical_default("(next_id())::integer", None) != canonical_default("next_id()", None)


def test_a_quoted_number_is_the_number() -> None:
    assert canonical_default("'1.50'::numeric", "numeric(10,2)") == "1.50"


def test_text_pglast_rejects_raises_for_the_caller_to_decide() -> None:
    """Drift falls back to comparing text; the reader does not guess."""
    with pytest.raises(pglast.parser.ParseError):
        canonical_default("CAST(", "text")
