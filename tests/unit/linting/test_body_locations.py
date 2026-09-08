"""Which file, and which line, a diagnosis about a routine belongs on (#245).

``plpgsql_check`` answers from the catalog, and the catalog does not know which
file a routine was written in. The join between the two is what turns "something
is wrong in ``app.fn_widget_pk``" into a location a reader can open, and it has
two awkward halves:

- **the key.** PostgreSQL spells argument types its own way — a ``varchar`` in
  the DDL is ``character varying`` in the catalog — so the two sides agree on
  the name and the *number* of input arguments, not on their spelling.
- **the line.** ``plpgsql_check`` counts from the body's first line, exactly as
  ``parse_plpgsql`` does, so both go through the one conversion in
  ``references.file_line`` rather than each carrying its own.

Where the join cannot be certain — two overloads of one name with the same
argument count — no location is better than the wrong file.
"""

from __future__ import annotations

from confiture.core.linting import bodies
from confiture.core.linting.schema_linter import RuleSeverity

WIDGET = """CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE app.tb_widget (pk_widget BIGINT PRIMARY KEY, name TEXT NOT NULL);
CREATE FUNCTION app.fn_widget_pk(p_name TEXT) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE
    v_pk UUID;
BEGIN
    SELECT pk_widget INTO v_pk FROM app.tb_widget WHERE name = p_name;
    RETURN v_pk;
END;
$$;
"""


def _diagnosis(**overrides) -> bodies.Diagnosis:
    fields = {
        "schema": "app",
        "name": "fn_widget_pk",
        "arity": 1,
        "kind": "function",
        "identity": "app.fn_widget_pk(text)",
        "body_line": 5,
        "level": "warning",
        "sqlstate": "42804",
        "message": "target type is different type than source type",
        "hint": 'cast "bigint" value to "uuid" type',
    }
    return bodies.Diagnosis(**{**fields, **overrides})


class TestTheKey:
    def test_a_routine_is_found_by_schema_name_and_argument_count(self) -> None:
        where = bodies.locations([("db/schema/010.sql", WIDGET)])

        assert bodies.locate(where, _diagnosis()) is not None

    def test_the_argument_count_ignores_how_a_type_is_spelled(self) -> None:
        """``varchar`` in the DDL is ``character varying`` in the catalog."""
        sql = (
            "CREATE FUNCTION app.fn_f(a VARCHAR(50), b NUMERIC(10,2)) RETURNS void "
            "LANGUAGE plpgsql AS $$ BEGIN END $$;\n"
        )
        where = bodies.locations([("db/schema/010.sql", sql)])

        found = bodies.locate(where, _diagnosis(name="fn_f", arity=2, identity="app.fn_f(...)"))

        assert found is not None and found.file == "db/schema/010.sql"

    def test_out_parameters_are_not_part_of_the_count(self) -> None:
        """``pronargs`` counts input arguments, and so does the signature."""
        sql = (
            "CREATE PROCEDURE app.pr_p(IN a bigint, OUT b int) "
            "LANGUAGE plpgsql AS $$ BEGIN END $$;\n"
        )
        where = bodies.locations([("db/schema/010.sql", sql)])

        assert bodies.locate(where, _diagnosis(name="pr_p", arity=1, kind="procedure")) is not None

    def test_a_routine_created_without_a_schema_still_matches(self) -> None:
        """Which schema an unqualified ``CREATE`` lands in is the build's answer, not the file's."""
        sql = "CREATE FUNCTION fn_f() RETURNS void LANGUAGE plpgsql AS $$ BEGIN END $$;\n"
        where = bodies.locations([("db/schema/010.sql", sql)])

        assert bodies.locate(where, _diagnosis(schema="public", name="fn_f", arity=0)) is not None

    def test_two_overloads_of_one_arity_yield_no_location(self) -> None:
        """A guess between two files is worse than saying nothing."""
        sql = (
            "CREATE FUNCTION app.fn_f(a int) RETURNS void LANGUAGE plpgsql AS $$ BEGIN END $$;\n"
            "CREATE FUNCTION app.fn_f(a text) RETURNS void LANGUAGE plpgsql AS $$ BEGIN END $$;\n"
        )
        where = bodies.locations([("db/schema/010.sql", sql)])

        assert bodies.locate(where, _diagnosis(name="fn_f", arity=1)) is None

    def test_overloads_of_different_arities_are_told_apart(self) -> None:
        sql = (
            "CREATE FUNCTION app.fn_f() RETURNS void LANGUAGE plpgsql AS $$ BEGIN END $$;\n"
            "CREATE FUNCTION app.fn_f(a int) RETURNS void LANGUAGE plpgsql AS $$ BEGIN END $$;\n"
        )
        where = bodies.locations([("db/schema/010.sql", sql)])

        found = bodies.locate(where, _diagnosis(name="fn_f", arity=1))

        assert found is not None and found.line == 2


class TestTheLine:
    def test_a_body_line_is_placed_on_the_file(self) -> None:
        """The body starts on file line 4, so its line 5 is file line 8."""
        where = bodies.locations([("db/schema/010.sql", WIDGET)])

        assert bodies.locate(where, _diagnosis()).at(5) == 8

    def test_a_diagnosis_about_the_whole_routine_gets_the_create_s_line(self) -> None:
        """ "control reached end of function without RETURN" carries no line of its own."""
        where = bodies.locations([("db/schema/010.sql", WIDGET)])

        assert bodies.locate(where, _diagnosis()).at(None) == 3

    def test_an_unlocatable_body_falls_back_to_the_create(self) -> None:
        at = bodies.Location(file="db/schema/010.sql", line=12, body_line=None)

        assert at.at(5) == 12


class TestTheFinding:
    def test_a_real_sqlstate_is_body_001_at_warning(self) -> None:
        where = bodies.locations([("db/schema/010.sql", WIDGET)])

        found = bodies.findings([_diagnosis()], where)

        assert (found[0].rule_id, found[0].severity) == ("body_001", RuleSeverity.WARNING)

    def test_sqlstate_00000_is_body_002_at_info(self) -> None:
        """The analyser's own opinion about a body that works, not a body that fails."""
        where = bodies.locations([("db/schema/010.sql", WIDGET)])

        found = bodies.findings(
            [_diagnosis(sqlstate="00000", message='unused variable "v_pk"', hint=None)], where
        )

        assert (found[0].rule_id, found[0].severity) == ("body_002", RuleSeverity.INFO)

    def test_the_message_quotes_postgresql_and_names_the_analyser(self) -> None:
        found = bodies.findings([_diagnosis()], {})

        assert found[0].message == (
            "plpgsql_check on 'app.fn_widget_pk(text)': "
            "target type is different type than source type (SQLSTATE 42804)"
        )

    def test_an_opinion_carries_no_sqlstate_because_it_has_none(self) -> None:
        found = bodies.findings([_diagnosis(sqlstate="00000", message="unused variable")], {})

        assert "SQLSTATE" not in found[0].message

    def test_the_suggested_fix_is_the_analyser_s_own_hint(self) -> None:
        found = bodies.findings([_diagnosis()], {})

        assert found[0].suggested_fix == 'cast "bigint" value to "uuid" type'

    def test_a_routine_no_file_claims_still_reports_without_a_location(self) -> None:
        """A routine an extension or a migration created is still a body that fails."""
        found = bodies.findings([_diagnosis()], {})

        assert (found[0].file_path, found[0].line_number) == (None, None)

    def test_the_finding_names_the_routine_the_way_the_catalog_does(self) -> None:
        found = bodies.findings([_diagnosis()], {})

        assert found[0].object_name == "app.fn_widget_pk(text)"
