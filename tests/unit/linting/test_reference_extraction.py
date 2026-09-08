"""What a body names: ``core/linting/references.py`` (#246).

The reproduction in #246 is a routine that reads ``app.tv_summary`` and calls
``app.fn_refresh_summary``, neither of which any file creates. Finding that
needs the set of objects a body *references*, which confiture has never
computed — the inventory only ever recorded what a statement *creates*.

Extraction is pglast end to end. ``parse_plpgsql`` hands back every embedded
SQL fragment as a ``PLpgSQL_expr.query`` string with the line it is written on,
each fragment goes back through ``parse_sql``, and one walker collects
``RangeVar`` (relations) and ``FuncCall`` (routines). ``LANGUAGE sql`` bodies
and view definitions are SQL already and parse directly. The issue is explicit
that its own hand-rolled regex version "is crude and misses plenty" — so what
cannot be resolved statically, an ``EXECUTE`` of a built string above all, is
*declared* unresolvable rather than guessed at.
"""

from __future__ import annotations

from confiture.core.linting.references import Reference, referenced_objects

ISSUE_246 = """CREATE OR REPLACE FUNCTION app.fn_report()
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN SELECT id FROM app.tv_summary LOOP
        PERFORM app.fn_refresh_summary(r.id);
    END LOOP;
END;
$$;
"""


def _names(refs: list[Reference]) -> set[tuple[str | None, str]]:
    return {(r.schema, r.name) for r in refs}


def test_the_issue_reproduction_yields_both_names() -> None:
    """#246's own example: one relation and one routine, neither created anywhere."""
    refs = referenced_objects(ISSUE_246)

    assert _names(refs) == {("app", "tv_summary"), ("app", "fn_refresh_summary")}


def test_a_relation_and_a_routine_are_told_apart() -> None:
    """A ``FROM`` names a relation and a call names a routine; the tiers differ."""
    refs = {(r.schema, r.name): r.kind for r in referenced_objects(ISSUE_246)}

    assert refs == {("app", "tv_summary"): "relation", ("app", "fn_refresh_summary"): "routine"}


def test_lines_are_body_relative() -> None:
    """``parse_plpgsql`` counts from the body's first line; that is what is reported.

    Body line 1 is the remainder of the ``$$`` line, so ``FOR`` is body line 5
    and ``PERFORM`` body line 6 — three and two lines short of the file, which
    is the conversion the rule owns.
    """
    lines = {r.name: r.line for r in referenced_objects(ISSUE_246)}

    assert lines == {"tv_summary": 5, "fn_refresh_summary": 6}


def test_every_reference_names_the_object_that_makes_it() -> None:
    """A finding is per referencing object: the routine is what the reader opens."""
    referrers = {r.referrer for r in referenced_objects(ISSUE_246)}

    assert referrers == {"app.fn_report()"}


def test_a_language_sql_body_parses_directly() -> None:
    """No plpgsql involved: the body is one SQL statement and pglast reads it whole."""
    sql = """CREATE FUNCTION app.fn_ids() RETURNS SETOF bigint LANGUAGE sql AS $$
    SELECT id FROM app.tb_missing
$$;
"""

    assert _names(referenced_objects(sql)) == {("app", "tb_missing")}


def test_an_unqualified_name_comes_back_and_is_the_rule_s_to_decline() -> None:
    """``count(*)`` is a reference; whether it can be *resolved* is a later question.

    Deciding that here would put the ``search_path`` question in the walker,
    where there is no configuration to answer it with.
    """
    sql = """CREATE FUNCTION app.fn_count() RETURNS bigint LANGUAGE sql AS $$
    SELECT count(*) FROM app.tb_missing
$$;
"""

    assert (None, "count") in _names(referenced_objects(sql))


def test_a_view_definition_is_a_body_too() -> None:
    """``CREATE VIEW`` names its relations in the statement itself."""
    sql = "CREATE VIEW app.v_report AS SELECT id FROM app.tb_missing;\n"

    refs = referenced_objects(sql)

    assert _names(refs) == {("app", "tb_missing")}
    assert {r.referrer for r in refs} == {"app.v_report"}


def test_a_materialized_view_definition_is_read_the_same_way() -> None:
    sql = "CREATE MATERIALIZED VIEW app.mv_report AS SELECT id FROM app.tb_missing;\n"

    assert _names(referenced_objects(sql)) == {("app", "tb_missing")}


def test_an_execute_of_a_built_string_is_declared_unresolvable() -> None:
    """The one case the issue calls out: a dynamic statement is not statically knowable.

    It is returned as a reference marked ``dynamic`` rather than dropped in the
    walker, so the rule declines it explicitly and a reader can see that the
    body was read and one statement in it could not be.
    """
    sql = """CREATE FUNCTION app.fn_dyn(t text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE 'SELECT 1 FROM ' || quote_ident(t);
END;
$$;
"""

    refs = referenced_objects(sql)

    assert [r.dynamic for r in refs] == [True]
    assert refs[0].line == 3


def test_nothing_inside_a_dynamic_statement_is_guessed_at() -> None:
    """``format('SELECT * FROM app.other')`` names no object the rule can check."""
    sql = """CREATE FUNCTION app.fn_dyn() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format('SELECT * FROM app.other');
END;
$$;
"""

    refs = referenced_objects(sql)

    assert ("app", "other") not in _names(refs)
    assert all(r.dynamic for r in refs)


def test_a_cte_is_not_a_relation() -> None:
    """A ``WITH`` name lives for one statement; no file creates it and none should."""
    sql = """CREATE VIEW app.v_c AS
WITH recent AS (SELECT id FROM app.tb_missing)
SELECT id FROM recent;
"""

    assert _names(referenced_objects(sql)) == {("app", "tb_missing")}


def test_dml_inside_a_body_references_its_target() -> None:
    """An ``INSERT`` target is as much a reference as a ``FROM``."""
    sql = """CREATE FUNCTION app.fn_log() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO app.tb_log(x) VALUES (1);
    UPDATE app.tb_state SET a = 1;
END;
$$;
"""

    assert _names(referenced_objects(sql)) == {("app", "tb_log"), ("app", "tb_state")}


def test_a_statement_that_creates_nothing_with_a_body_yields_nothing() -> None:
    """A plain ``CREATE TABLE`` has no body to read."""
    assert referenced_objects("CREATE TABLE app.tb_t (id int PRIMARY KEY);\n") == []


def test_a_c_language_routine_has_no_sql_body() -> None:
    """``AS 'module', 'symbol'`` names a shared object, not SQL to parse."""
    sql = "CREATE FUNCTION app.fn_c() RETURNS int LANGUAGE c AS 'mylib', 'fn_c';\n"

    assert referenced_objects(sql) == []


def test_unparseable_sql_yields_nothing_rather_than_raising() -> None:
    """The linter reports a parse failure once, as ``UNPARSEABLE``; this is not its job."""
    assert referenced_objects("CREATE FUNCTION (((;") == []
