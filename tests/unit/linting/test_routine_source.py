"""The statement that defines a routine, found by the inventory's identity and returned as written.

``migrate fix-signatures --mode apply`` executes this text, so it is the author's
statement, never a re-rendering. Which statement it is, is the inventory's answer
to "is this (schema, name)": an unqualified name lives in ``DEFAULT_SCHEMA``
(#313), where a regex over ``[schema.]name(`` matched it in every schema.
"""

from __future__ import annotations

from confiture.core.linting.inventory import routine_source

SQL = """
CREATE TABLE users (id bigint);

CREATE OR REPLACE FUNCTION public.get_user(user_id bigint)
RETURNS TABLE(id bigint, name text) AS $$
  SELECT id, name FROM users WHERE id = user_id;
$$ LANGUAGE sql;

CREATE FUNCTION app.set_status(p text) RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;

CREATE PROCEDURE app.tidy() LANGUAGE sql AS $$ SELECT 1 $$;

CREATE VIEW app.get_user AS SELECT 1 AS id;
"""


def test_finds_a_qualified_function_as_written() -> None:
    found = routine_source(SQL, "public", "get_user")
    assert found is not None
    assert found.startswith("CREATE OR REPLACE FUNCTION public.get_user(user_id bigint)")
    assert "SELECT id, name FROM users" in found


def test_the_text_is_what_the_lexer_splits_out() -> None:
    """Leading comments included, semicolon not: the text ``fix-signatures`` always printed."""
    from confiture.core.sql_lexer import split_statements

    sql = "CREATE TABLE t (a int);\n-- the one that matters\nCREATE FUNCTION f() RETURNS int\nLANGUAGE sql AS $$ SELECT 1 $$;\n"
    assert routine_source(sql, None, "f") == split_statements(sql)[1]


def test_finds_a_procedure() -> None:
    assert routine_source(SQL, "app", "tidy") is not None


def test_a_view_of_the_same_name_is_not_a_routine() -> None:
    assert routine_source(SQL, "app", "get_user") is None


def test_an_unqualified_name_is_in_the_default_schema() -> None:
    sql = "CREATE FUNCTION get_user(id bigint) RETURNS void AS $$ $$ LANGUAGE sql;"
    assert routine_source(sql, "public", "get_user") is not None
    assert routine_source(sql, "app", "get_user") is None


def test_nothing_when_nothing_matches() -> None:
    assert routine_source(SQL, "public", "no_such_fn") is None
    assert routine_source("", "public", "get_user") is None
