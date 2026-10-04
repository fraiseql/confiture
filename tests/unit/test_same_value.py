"""``ddl_walk.same_value``: one value, whichever side wrote it.

A default reaches a comparison twice — as the DDL wrote it and as ``pg_get_expr``
gives it back — and PostgreSQL stores it analysed: ``'x'`` in a ``text`` column comes
back ``'x'::text``, ``1 + 2`` comes back ``(1 + 2)``, ``TRUE`` comes back ``true``.
Compared as text, 10 of 24 shapes agreed; read as a parse tree, all 24 do. A
constant is opaque to a parse tree, so it is compared as the server spells it
(:class:`ConstantSpellings`, read by ``server_constants``) and as its type reads: a
number only where the type is a number. What is measured against a real server is
``tests/integration/test_default_comparison_is_measured.py``; this is the rule, one
row per rewrite.
"""

import pytest

from confiture.core.ddl_walk import AS_WRITTEN, ConstantSpellings, same_value, typed_constants

#: ``(column type, as the DDL writes it, as the catalog gives it back)``.
SAME = [
    ("text", "'x'", "'x'::text"),
    ("text", "'active'", "'active'::text"),
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
    ("real", "1.5", "'1.5'::real"),
    ("text", "123", "'123'::text"),
]


def _same(column_type: str | None, one: str | None, other: str | None, **kwargs: object) -> bool:
    return same_value(one, other, slot="default", types=(column_type, column_type), **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(("column_type", "written", "stored"), SAME)
def test_a_default_and_its_stored_form_are_one_value(
    column_type: str, written: str, stored: str
) -> None:
    assert _same(column_type, written, stored)


@pytest.mark.parametrize(
    ("column_type", "one", "other"),
    [
        ("text", "'x'", "'y'::text"),
        ("integer", "0", "1"),
        ("boolean", "true", "false"),
        ("timestamptz", "now()", "CURRENT_TIMESTAMP"),
        ("text", "lower('ABC')", "upper('ABC'::text)"),
        ("jsonb", """'{"a": 1}'::jsonb""", """'{"a": 2}'::jsonb"""),
    ],
)
def test_two_values_that_differ_stay_different(column_type: str, one: str, other: str) -> None:
    assert not _same(column_type, one, other)


def test_no_default_is_the_same_as_no_default() -> None:
    assert _same("text", None, None)
    assert not _same("text", None, "'x'")


def test_null_is_no_default() -> None:
    """PostgreSQL stores no default for ``DEFAULT NULL``, so the two are one."""
    assert _same("text", "NULL", None)
    assert _same("text", "NULL::text", None)


def test_an_outer_cast_to_the_columns_own_type_is_dropped() -> None:
    assert _same("integer", "(next_id())::integer", "next_id()")


def test_a_cast_to_another_type_is_kept() -> None:
    """Only the analyser's cast to the column's type is noise; any other one says something."""
    assert not _same("integer", "(next_id())::bigint", "next_id()")


def test_without_a_column_type_only_the_literal_casts_go() -> None:
    assert _same(None, "lower('ABC'::text)", "lower('ABC')")
    assert not _same(None, "(next_id())::integer", "next_id()")


def test_a_quoted_number_is_the_number_where_its_type_is_a_number() -> None:
    assert _same("numeric(10,2)", "'1.50'::numeric", "1.50")


def test_a_quoted_number_stays_text_where_its_type_is_text() -> None:
    """``'123'::text`` and ``123`` are one value only while both columns are ``text``."""
    assert not same_value("'123'::text", "123", slot="default", types=("text", "integer"))
    assert not _same(None, "'123'::text", "123")


def test_a_constant_is_compared_as_the_server_spells_it() -> None:
    """#564: PostgreSQL stores a jsonb object with its keys in jsonb's order."""
    written = """'{"max_attempts": 3, "backoff": "x"}'::jsonb"""
    stored = """'{"backoff": "x", "max_attempts": 3}'::jsonb"""
    spelled = ConstantSpellings(
        {
            (
                """{"max_attempts": 3, "backoff": "x"}""",
                "jsonb",
            ): """{"backoff": "x", "max_attempts": 3}"""
        }
    )
    assert not _same("jsonb", written, stored)
    assert _same("jsonb", written, stored, constants=spelled)


def test_a_bare_constant_takes_the_columns_type() -> None:
    spelled = ConstantSpellings({("t", "boolean"): "true", ("2024-1-1", "date"): "2024-01-01"})
    assert _same("boolean", "'t'", "true", constants=spelled)
    assert _same("date", "'2024-1-1'", "'2024-01-01'::date", constants=spelled)


def test_the_constants_a_server_is_asked_to_spell() -> None:
    """Each constant whose type is known: a cast's, or the column's at the top."""
    assert typed_constants("""'{"b": 1}'::jsonb""", "jsonb") == {("""{"b": 1}""", "jsonb")}
    assert typed_constants("'t'", "boolean") == {("t", "boolean")}
    assert typed_constants("'{1, 2}'", "int[]") == {("{1, 2}", "integer[]")}
    assert typed_constants("'1.5'", "numeric(10,2)") == {("1.5", "numeric")}
    assert typed_constants("lower('ABC')", "text") == set()
    assert typed_constants("now()", "timestamptz") == set()
    assert typed_constants(None, "text") == set()


def test_text_pglast_rejects_is_compared_as_written() -> None:
    """The reader does not guess: two spellings it cannot read are two values."""
    assert _same("text", "CAST(", "CAST(")
    assert not _same("text", "CAST(", "CAST( ")


def test_as_written_spells_nothing() -> None:
    assert AS_WRITTEN.spell("t", "boolean") == "t"
