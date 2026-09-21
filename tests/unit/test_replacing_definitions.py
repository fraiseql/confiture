"""The statement ``fix-signatures`` runs to create a routine: found by identity, safe to re-run.

Which routine a statement defines is the inventory's answer (an unqualified name
lives in ``DEFAULT_SCHEMA``, #313; a view is not a routine), and the statement is
``ddl_objects``' re-appliable rendering, because the author's ``CREATE FUNCTION``
fails on a routine that exists — which is what a body fix replaces.
"""

from __future__ import annotations

import pglast

from confiture.core.function_signature_drift import (
    declared_routines,
    definition_of,
    printed_signature,
    replacing_definitions,
)
from confiture.core.schema_model import Routine

SQL = """
CREATE TABLE users (id bigint);

CREATE FUNCTION public.get_user(user_id bigint)
RETURNS TABLE(id bigint, name text) AS $$
  SELECT id, name FROM users WHERE id = user_id;
$$ LANGUAGE sql;

CREATE FUNCTION public.get_user(user_name text) RETURNS bigint AS $$ SELECT 1 $$ LANGUAGE sql;

CREATE PROCEDURE app.tidy() LANGUAGE sql AS $$ SELECT 1 $$;

CREATE VIEW app.get_user AS SELECT 1 AS id;
"""


def _routine(sql: str, signature: str) -> Routine:
    (found,) = [r for r in declared_routines(sql) if printed_signature(r) == signature]
    return found


def test_a_plain_create_becomes_a_create_or_replace_with_its_body_verbatim() -> None:
    create = definition_of(replacing_definitions(SQL), _routine(SQL, "public.get_user(bigint)"))

    assert create is not None
    assert create.startswith("CREATE OR REPLACE FUNCTION public.get_user(user_id bigint)")
    assert "\n  SELECT id, name FROM users WHERE id = user_id;\n" in create
    assert pglast.parse_sql(create)


def test_each_overload_is_its_own_statement() -> None:
    create = definition_of(replacing_definitions(SQL), _routine(SQL, "public.get_user(text)"))

    assert create is not None
    assert "get_user(user_name text) RETURNS bigint" in create


def test_a_procedure_is_found() -> None:
    create = definition_of(replacing_definitions(SQL), _routine(SQL, "app.tidy()"))

    assert create is not None
    assert create.startswith("CREATE OR REPLACE PROCEDURE app.tidy()")


def test_a_view_of_the_same_name_is_not_a_routine() -> None:
    assert "app.get_user" not in replacing_definitions(SQL)


def test_an_unqualified_name_is_in_the_default_schema() -> None:
    sql = "CREATE FUNCTION get_user(id bigint) RETURNS void AS $$ $$ LANGUAGE sql;"

    assert set(replacing_definitions(sql)) == {"public.get_user"}


def test_the_last_definition_is_the_one_the_build_leaves() -> None:
    sql = (
        "CREATE FUNCTION f() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n"
        "CREATE OR REPLACE FUNCTION f() RETURNS int LANGUAGE sql AS $$ SELECT 2 $$;\n"
    )

    create = definition_of(replacing_definitions(sql), _routine(sql, "public.f()"))

    assert create is not None
    assert "SELECT 2" in create


def test_nothing_when_nothing_matches() -> None:
    elsewhere = Routine(name="get_user", schema="other")

    assert definition_of(replacing_definitions(SQL), elsewhere) is None
    assert replacing_definitions("") == {}
