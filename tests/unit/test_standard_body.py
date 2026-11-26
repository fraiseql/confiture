"""A SQL-standard body (``RETURN expr`` / ``BEGIN ATOMIC … END``) in the model.

PostgreSQL parses such a body at ``CREATE`` and keeps it analysed
(``pg_proc.prosqlbody``), never as the text between ``AS`` quotes. The model
holds it as ``Routine.body`` with ``standard_body`` set: the tree's printed by
pglast, the database's by ``pg_get_function_sqlbody``. Two trees compare it as
written; a tree and a database compare that one exists (``analysed_expressions``)
unless the tree is materialised and both come through PostgreSQL's deparser.
"""

from dataclasses import replace

from confiture.core.schema_model import ALL_PARITY_RULES, Routine, parity_routine
from confiture.core.schema_sources import read_schema


def routine(sql: str) -> Routine:
    (found,) = read_schema(sql).model.all_routines()
    return found


def test_a_return_body_is_read_as_pglast_prints_it() -> None:
    found = routine("CREATE FUNCTION f(a int) RETURNS int LANGUAGE sql IMMUTABLE RETURN a+1;")
    assert (found.body, found.standard_body) == ("RETURN a + 1", True)


def test_a_begin_atomic_body_is_read_whole() -> None:
    found = routine(
        "CREATE FUNCTION f(a int) RETURNS int LANGUAGE sql BEGIN ATOMIC SELECT a; SELECT 2; END;"
    )
    assert (found.body, found.standard_body) == ("BEGIN ATOMIC SELECT a; SELECT 2; END", True)


def test_a_quoted_body_is_not_standard() -> None:
    found = routine("CREATE FUNCTION f() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;")
    assert (found.body, found.standard_body) == (" SELECT 1 ", False)


def test_two_trees_see_a_changed_return_body() -> None:
    before = routine("CREATE FUNCTION f(t text) RETURNS text LANGUAGE sql RETURN lower(t);")
    after = routine("CREATE FUNCTION f(t text) RETURNS text LANGUAGE sql RETURN upper(t);")
    assert parity_routine(before, frozenset()) != parity_routine(after, frozenset())


def test_against_a_database_a_standard_body_compares_as_present() -> None:
    tree = routine("CREATE FUNCTION f(t text) RETURNS text LANGUAGE sql RETURN lower(t);")
    analysed = replace(tree, body="RETURN lower(t)")  # however the server deparses it
    respelled = replace(tree, body="RETURN lower((t)::text)")
    assert parity_routine(analysed, ALL_PARITY_RULES) == parity_routine(respelled, ALL_PARITY_RULES)


def test_a_standard_body_never_equals_a_quoted_one() -> None:
    tree = routine("CREATE FUNCTION f(t text) RETURNS text LANGUAGE sql RETURN lower(t);")
    quoted = replace(tree, body="SELECT lower(t)", standard_body=False)
    assert parity_routine(tree, ALL_PARITY_RULES) != parity_routine(quoted, ALL_PARITY_RULES)


def test_body_drift_leaves_a_standard_body_to_the_engine() -> None:
    """The text detector reads a tree against a database: two printers, so no verdict."""
    from confiture.core.function_body_drift import FunctionBodyDriftDetector

    tree = routine(
        "CREATE FUNCTION app.fold(text) RETURNS text LANGUAGE sql IMMUTABLE "
        "RETURN public.unaccent('\"public\".unaccent'::regdictionary, $1);"
    )
    live = replace(tree, body="RETURN unaccent('unaccent'::regdictionary, $1)")
    report = FunctionBodyDriftDetector().compare([tree], [live])
    assert not report.has_drift
