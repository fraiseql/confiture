"""``-- confiture:creates <relation>``: what a migration says it creates, matched as written."""

from confiture.core.created_relations import creates_line, declared
from confiture.core.sql_lexer import directives


def test_a_creates_directive_declares_its_relation() -> None:
    sql = "-- confiture:creates users\nCREATE TABLE users (id int);\n"
    assert declared(sql) == frozenset({(None, "users")})


def test_a_qualified_directive_declares_only_the_qualified_name() -> None:
    sql = "-- confiture:creates app.users\nCREATE TABLE app.users (id int);\n"
    assert declared(sql) == frozenset({("app", "users")})


def test_an_unqualified_directive_declares_only_the_unqualified_name() -> None:
    sql = "-- confiture:creates users\nCREATE TABLE public.users (id int);\n"
    assert ("public", "users") not in declared(sql)


def test_case_is_folded_as_postgresql_folds_it() -> None:
    sql = '-- confiture:creates App.Users\n-- confiture:creates "Mixed"\nSELECT 1;\n'
    assert declared(sql) == frozenset({("app", "users"), (None, "Mixed")})


def test_an_argument_of_three_parts_or_not_a_name_declares_nothing() -> None:
    sql = (
        "-- confiture:creates a.b.c\n"
        "-- confiture:creates a b\n"
        "-- confiture:creates t;\n"
        "-- confiture:creates\n"
        "SELECT 1;\n"
    )
    assert declared(sql) == frozenset()


def test_a_directive_inside_a_dollar_body_or_copy_block_is_not_read() -> None:
    sql = (
        "CREATE FUNCTION f() RETURNS int LANGUAGE sql AS $$\n"
        "-- confiture:creates hidden\n"
        "SELECT 1\n"
        "$$;\n"
        "COPY t (a) FROM stdin;\n"
        "-- confiture:creates copied\n"
        "\\.\n"
    )
    assert declared(sql) == frozenset()


def test_creates_line_round_trips_through_declared() -> None:
    assert declared(creates_line("app.tb_order") + "\nSELECT 1;\n") == frozenset(
        {("app", "tb_order")}
    )


def test_creates_line_keeps_a_name_with_a_newline_inside_the_comment() -> None:
    line = creates_line('app."a\nb"')
    assert "\n" not in line
    [directive] = directives(line + "\nSELECT 1;\n")
    assert directive.name == "creates"
    assert directive.argument == 'app."a\\nb"'
