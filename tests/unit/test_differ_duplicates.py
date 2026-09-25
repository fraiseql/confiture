"""A collapse is a finding, not a silence (#313, the issue's item 3).

Two definitions of one ``(schema, name)`` in one tree is a genuine duplicate —
#313's defect with the schema taken out of it: an identity two objects share,
resolved by "last one wins" rather than by asking which one the build keeps.

``confiture build`` keeps the **first** definition when the later ones are
``IF NOT EXISTS`` no-ops, and fails at the later statement when one is a plain
``CREATE``. The differ kept the last, unconditionally, and compared a table the
database does not have.

The answer is ``core.linting.duplicates.wins`` — ``build_001``'s own rule — not
a second one written here.
"""

from __future__ import annotations

from confiture.core.differ import SchemaDiffer


class TestTheDifferKeepsTheDefinitionTheBuildKeeps:
    def test_a_later_if_not_exists_is_a_no_op(self) -> None:
        parsed = SchemaDiffer().parse_schema(
            "CREATE TABLE t (id INT, a TEXT);\nCREATE TABLE IF NOT EXISTS t (id INT, b TEXT);"
        )
        assert [(t.name, [c.name for c in t.columns]) for t in parsed.tables] == [
            ("t", ["id", "a"])
        ]

    def test_the_column_added_to_the_first_definition_is_reported(self) -> None:
        old = "CREATE TABLE t (id INT, a TEXT);\nCREATE TABLE IF NOT EXISTS t (id INT, b TEXT);"
        new = (
            "CREATE TABLE t (id INT, a TEXT, c TEXT);\n"
            "CREATE TABLE IF NOT EXISTS t (id INT, b TEXT);"
        )
        assert [str(c) for c in SchemaDiffer().compare(old, new).changes] == ["ADD COLUMN t.c"]

    def test_a_second_plain_create_is_a_conflict_and_the_first_still_stands(self) -> None:
        """The build fails at the second statement, so the first is what exists."""
        parsed = SchemaDiffer().parse_schema(
            "CREATE TABLE t (id INT, a TEXT);\nCREATE TABLE t (id INT, b TEXT);"
        )
        assert [(t.name, [c.name for c in t.columns]) for t in parsed.tables] == [
            ("t", ["id", "a"])
        ]
        (warning,) = parsed.warnings
        assert "fails the build" in warning.message

    def test_two_schemas_are_not_a_duplicate(self) -> None:
        """The control: after Phases 01-02 a collapse means a real duplicate."""
        parsed = SchemaDiffer().parse_schema(
            "CREATE TABLE tenant.t (id INT);\nCREATE TABLE etl.t (id INT);"
        )
        assert len(parsed.tables) == 2
        assert parsed.warnings == []

    def test_a_tree_with_no_duplicates_warns_about_nothing(self) -> None:
        parsed = SchemaDiffer().parse_schema("CREATE TABLE t (id INT);\nCREATE TABLE u (id INT);")
        assert parsed.warnings == []

    def test_a_duplicate_enum_type_and_sequence_collapse_too(self) -> None:
        parsed = SchemaDiffer().parse_schema(
            "CREATE TYPE e AS ENUM ('a');\nCREATE TYPE e AS ENUM ('b');\n"
            "CREATE SEQUENCE s;\nCREATE SEQUENCE IF NOT EXISTS s;"
        )
        assert [e.values for e in parsed.enum_types] == [("a",)]
        assert len(parsed.sequences) == 1
        assert {w.message.split("'")[1] for w in parsed.warnings} == {"e", "s"}


class TestTheCollapseIsReported:
    def test_the_warning_names_the_identity_the_count_and_the_definition_used(self) -> None:
        parsed = SchemaDiffer().parse_schema(
            "CREATE TABLE tenant.t (id INT);\nCREATE TABLE IF NOT EXISTS tenant.t (id INT);"
        )
        (warning,) = parsed.warnings
        assert warning.code == "DIFFER_402"
        assert warning.severity == "warning"
        assert "tenant.t" in warning.message
        assert "2 times" in warning.message
        assert "first" in warning.message

    def test_a_diff_carries_the_warnings_of_both_sides_once_each(self) -> None:
        duplicated = "CREATE TABLE t (id INT);\nCREATE TABLE IF NOT EXISTS t (id INT);"
        diff = SchemaDiffer().compare(duplicated, duplicated)
        assert diff.changes == []
        assert len(diff.warnings) == 1

    def test_a_duplicate_on_one_side_only_is_still_reported(self) -> None:
        diff = SchemaDiffer().compare(
            "CREATE TABLE t (id INT);",
            "CREATE TABLE t (id INT);\nCREATE TABLE IF NOT EXISTS t (id INT);",
        )
        assert len(diff.warnings) == 1

    def test_a_clean_diff_has_an_empty_warnings_list_not_a_missing_one(self) -> None:
        diff = SchemaDiffer().compare("CREATE TABLE t (id INT);", "CREATE TABLE t (id INT);")
        assert diff.warnings == []


class TestThePayloadAndTheGate:
    """The warning reaches the JSON envelope and the command the issue was filed against."""

    def test_the_diff_payload_carries_warnings(self) -> None:
        from confiture.models.results import MigrateDiffResult

        payload = MigrateDiffResult(success=True, has_changes=False).to_dict()
        assert payload["warnings"] == []

    def test_a_duplicate_reaches_the_diff_payload(self) -> None:
        from confiture.models.results import MigrateDiffResult

        diff = SchemaDiffer().compare(
            "CREATE TABLE t (id INT);",
            "CREATE TABLE t (id INT);\nCREATE TABLE IF NOT EXISTS t (id INT);",
        )
        payload = MigrateDiffResult(
            success=True,
            has_changes=diff.has_changes(),
            warnings=diff.warnings,
        ).to_dict()
        assert [w["code"] for w in payload["warnings"]] == ["DIFFER_402"]
        assert payload["warnings"][0]["severity"] == "warning"

    def test_the_accompaniment_report_publishes_a_warnings_channel(self) -> None:
        """``migrate validate --require-migration`` is where #313 was reported from.

        A warning that stopped at the ``SchemaDiff`` boundary would not reach the
        one command the issue is about. Present and empty, never absent.
        """
        from confiture.models.git import MigrationAccompanimentReport

        report = MigrationAccompanimentReport(has_ddl_changes=False, has_new_migrations=False)
        assert report.warnings == []
        assert report.to_dict()["warnings"] == []

    def test_a_duplicate_reaches_the_accompaniment_payload(self) -> None:
        from confiture.models.git import MigrationAccompanimentReport

        diff = SchemaDiffer().compare(
            "CREATE TABLE t (id INT);",
            "CREATE TABLE t (id INT);\nCREATE TABLE IF NOT EXISTS t (id INT);",
        )
        report = MigrationAccompanimentReport(
            has_ddl_changes=False, has_new_migrations=False, warnings=diff.warnings
        )
        assert [w["code"] for w in report.to_dict()["warnings"]] == ["DIFFER_402"]


class TestAnObjectComparedByDefinitionCollapsesToo:
    """A view, routine or trigger defined twice is one object, reported once (#407).

    ``ddl_objects`` kept every definition of a bucket, so a view defined in two
    files was two ``ADD_VIEW`` changes and two ``CREATE`` statements in a
    generated migration, and no ``DIFFER_402`` said why.
    """

    TABLE = "CREATE TABLE t (id INT, a TEXT);\n"

    def test_a_view_defined_twice_is_added_once(self) -> None:
        new = self.TABLE + "CREATE VIEW v AS SELECT id FROM t;\n" * 2
        changes = SchemaDiffer().compare(self.TABLE, new).changes
        assert [str(c) for c in changes] == ["ADD VIEW v"]

    def test_the_view_defined_twice_is_reported(self) -> None:
        parsed = SchemaDiffer().parse_schema(
            self.TABLE + "CREATE VIEW v AS SELECT id FROM t;\n" * 2
        )
        (warning,) = parsed.warnings
        assert warning.code == "DIFFER_402"
        assert warning.message.startswith("View 'v' is defined 2 times")
        assert "fails the build" in warning.message

    def test_a_later_or_replace_wins(self) -> None:
        """The build runs both, so the object is the second definition."""
        old = self.TABLE + "CREATE VIEW v AS SELECT id FROM t;\n"
        new = old + "CREATE OR REPLACE VIEW v AS SELECT id, a FROM t;\n"
        (change,) = SchemaDiffer().compare(old, new).changes
        assert str(change) == "REPLACE VIEW v"
        (warning,) = SchemaDiffer().parse_schema(new).warnings
        assert "the comparison used the last definition" in warning.message

    def test_a_plain_second_create_keeps_the_first(self) -> None:
        """The build fails at the second statement, so the first is what exists."""
        old = self.TABLE + "CREATE VIEW v AS SELECT id FROM t;\n"
        new = old + "CREATE VIEW v AS SELECT id, a FROM t;\n"
        assert SchemaDiffer().compare(old, new).changes == []

    def test_a_routine_defined_twice_is_one_routine(self) -> None:
        body = "CREATE OR REPLACE FUNCTION f(x bigint) RETURNS int LANGUAGE sql AS 'SELECT 1';\n"
        respelled = body.replace("bigint", "int8")
        changes = SchemaDiffer().compare("", body + respelled).changes
        assert [str(c) for c in changes] == ["ADD FUNCTION f(bigint)"]
        (warning,) = SchemaDiffer().parse_schema(body + respelled).warnings
        # Named as the definition the build keeps: the second, spelled int8.
        assert warning.message.startswith("Function 'f(int8)' is defined 2 times")

    def test_two_overloads_are_not_a_duplicate(self) -> None:
        """The control: a bucket holds overloads, and they stay two."""
        sql = (
            "CREATE FUNCTION f(x bigint) RETURNS int LANGUAGE sql AS 'SELECT 1';\n"
            "CREATE FUNCTION f(x text) RETURNS int LANGUAGE sql AS 'SELECT 1';\n"
        )
        parsed = SchemaDiffer().parse_schema(sql)
        assert parsed.warnings == []
        assert len(SchemaDiffer().compare("", sql).changes) == 2

    def test_a_trigger_defined_twice_is_one_trigger(self) -> None:
        trigger = (
            "CREATE FUNCTION tf() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RETURN NEW; END';\n"
        )
        once = "CREATE TRIGGER trg BEFORE INSERT ON t FOR EACH ROW EXECUTE FUNCTION tf();\n"
        changes = SchemaDiffer().compare(self.TABLE + trigger, self.TABLE + trigger + once * 2)
        assert [str(c) for c in changes.changes] == ["ADD TRIGGER t.trg"]
