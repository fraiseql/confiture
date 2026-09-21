"""The schema objects the differ must not be silent about (issue #288).

``migrate validate --require-migration`` asks whether the schema tree changed in
a way a migrate-only environment will not receive. Until #288 it read tables,
enum types and sequences and nothing else, so a view added, dropped or redefined
— and a function, a trigger, an extension — passed the gate with a green tick.

These tests are written against ``SchemaDiffer.compare``, the public seam the
gate reaches through, rather than against the object collection underneath it:
what matters is that the change is *reported*, not which walker found it.
"""

from confiture.core.differ import SchemaDiffer
from confiture.models.schema import WireChange

BASE = "CREATE TABLE tb_user (pk_user BIGINT PRIMARY KEY, name TEXT);\n"


def changes_of(old_extra: str, new_extra: str) -> list[WireChange]:
    """The changes between two schemas that share :data:`BASE`."""
    return SchemaDiffer().compare(BASE + old_extra, BASE + new_extra).wire()


def types_of(old_extra: str, new_extra: str) -> list[str]:
    return [c.type for c in changes_of(old_extra, new_extra)]


class TestViewsAreSchemaObjects:
    """A view is an object a migrate-only environment has to be given."""

    def test_added_view_is_reported(self):
        assert "ADD_VIEW" in types_of("", "CREATE VIEW v_user AS SELECT pk_user FROM tb_user;")

    def test_dropped_view_is_reported(self):
        assert "DROP_VIEW" in types_of("CREATE VIEW v_user AS SELECT pk_user FROM tb_user;", "")

    def test_redefined_view_is_reported(self):
        """``CREATE OR REPLACE VIEW`` with a changed body is a change."""
        assert "REPLACE_VIEW" in types_of(
            "CREATE OR REPLACE VIEW v_user AS SELECT pk_user FROM tb_user;",
            "CREATE OR REPLACE VIEW v_user AS SELECT pk_user, name FROM tb_user;",
        )

    def test_reformatted_view_is_not_a_change(self):
        """Whitespace, case and comments are not a redefinition."""
        assert (
            types_of(
                "CREATE VIEW v_user AS SELECT pk_user FROM tb_user;",
                "-- the users, by key\nCREATE   VIEW v_user\n  AS\n  select pk_user\n  from tb_user;",
            )
            == []
        )

    def test_or_replace_alone_is_not_a_change(self):
        """A view gaining ``OR REPLACE`` defines the same view."""
        assert (
            types_of(
                "CREATE VIEW v_user AS SELECT pk_user FROM tb_user;",
                "CREATE OR REPLACE VIEW v_user AS SELECT pk_user FROM tb_user;",
            )
            == []
        )

    def test_added_materialized_view_is_reported(self):
        assert "ADD_MATVIEW" in types_of(
            "", "CREATE MATERIALIZED VIEW mv_user AS SELECT pk_user FROM tb_user;"
        )

    def test_dropped_materialized_view_is_reported(self):
        assert "DROP_MATVIEW" in types_of(
            "CREATE MATERIALIZED VIEW mv_user AS SELECT pk_user FROM tb_user;", ""
        )

    def test_create_table_as_is_not_a_materialized_view(self):
        """``CREATE TABLE AS`` shares a parse node with the matview; only one counts."""
        assert "ADD_MATVIEW" not in types_of(
            "", "CREATE TABLE tb_copy AS SELECT pk_user FROM tb_user;"
        )

    def test_a_view_and_a_table_of_the_same_name_are_two_objects(self):
        """The key is the kind as well as the name."""
        types = types_of("", "CREATE VIEW tb_user_x AS SELECT pk_user FROM tb_user;")
        assert "ADD_VIEW" in types
        assert "ADD_TABLE" not in types


class TestUnchangedSchemaIsStillQuiet:
    """The gate's value depends on it staying silent when nothing changed."""

    def test_identical_schema_with_views_reports_nothing(self):
        schema = (
            BASE
            + "CREATE VIEW v_user AS SELECT pk_user FROM tb_user;\n"
            + "CREATE MATERIALIZED VIEW mv_user AS SELECT pk_user FROM tb_user;\n"
        )
        assert SchemaDiffer().compare(schema, schema).changes == []


class TestRoutinesAreSchemaObjects:
    """A routine's identity is its signature, so an overload is another object."""

    FN = "CREATE FUNCTION fn_count() RETURNS BIGINT LANGUAGE sql AS $$ SELECT 1 $$;"

    def test_added_function_is_reported(self):
        assert "ADD_FUNCTION" in types_of("", self.FN)

    def test_dropped_function_is_reported(self):
        assert "DROP_FUNCTION" in types_of(self.FN, "")

    def test_changed_body_is_a_replace(self):
        assert "REPLACE_FUNCTION" in types_of(
            "CREATE OR REPLACE FUNCTION fn_c() RETURNS BIGINT LANGUAGE sql AS $$ SELECT 1 $$;",
            "CREATE OR REPLACE FUNCTION fn_c() RETURNS BIGINT LANGUAGE sql AS $$ SELECT 2 $$;",
        )

    def test_an_added_overload_is_an_addition_not_a_replacement(self):
        """``fn(int)`` beside ``fn()`` is a second object, not the first one changed."""
        types = types_of(
            self.FN,
            self.FN
            + "\nCREATE FUNCTION fn_count(p INT) RETURNS BIGINT LANGUAGE sql AS $$ SELECT 1 $$;",
        )
        assert types == ["ADD_FUNCTION"]

    def test_a_dropped_overload_is_a_drop_not_a_replacement(self):
        types = types_of(
            self.FN
            + "\nCREATE FUNCTION fn_count(p INT) RETURNS BIGINT LANGUAGE sql AS $$ SELECT 1 $$;",
            self.FN,
        )
        assert types == ["DROP_FUNCTION"]

    def test_a_respelled_parameter_type_is_one_object_not_a_drop_and_an_add(self):
        """``int8`` and ``bigint`` are one type, so ``fn(int8)`` is ``fn(bigint)`` (#275).

        It is reported as a ``REPLACE``, not as nothing: ``RawStream`` renders a
        type as the author spelled it, so the definitions differ textually even
        though PostgreSQL sees no change. Over-reporting is the safe direction
        here — the gate asks for a migration that turns out to be unnecessary.
        Under it lies the failure this must never make: telling an operator to
        ``DROP FUNCTION fn_c(bigint)`` and create ``fn_c(int8)``, which are the
        same function, and whose drop takes its dependents with it.
        """
        assert types_of(
            "CREATE FUNCTION fn_c(p BIGINT) RETURNS BIGINT LANGUAGE sql AS $$ SELECT 1 $$;",
            "CREATE FUNCTION fn_c(p INT8) RETURNS BIGINT LANGUAGE sql AS $$ SELECT 1 $$;",
        ) == ["REPLACE_FUNCTION"]

    def test_a_reformatted_routine_is_not_a_change(self):
        """What canonical rendering does buy: whitespace, case and comments."""
        assert (
            types_of(
                "CREATE FUNCTION fn_c() RETURNS BIGINT LANGUAGE sql AS $$ SELECT 1 $$;",
                "-- counts them\nCREATE   function fn_c()\n  RETURNS bigint\n  language sql\n  AS $$ SELECT 1 $$;",
            )
            == []
        )

    def test_added_procedure_is_reported(self):
        assert "ADD_PROCEDURE" in types_of(
            "", "CREATE PROCEDURE pr_do() LANGUAGE sql AS $$ SELECT 1 $$;"
        )

    def test_a_function_and_a_procedure_of_one_name_are_two_objects(self):
        types = types_of(
            self.FN, self.FN + "\nCREATE PROCEDURE fn_count() LANGUAGE sql AS $$ SELECT 1 $$;"
        )
        assert types == ["ADD_PROCEDURE"]

    def test_added_aggregate_is_reported(self):
        assert "ADD_AGGREGATE" in types_of(
            "", "CREATE AGGREGATE ag_sum (INT) (sfunc = int4pl, stype = INT);"
        )

    def test_create_operator_is_not_an_aggregate(self):
        """``DefineStmt`` is shared; only the aggregate spelling creates one here."""
        assert "ADD_AGGREGATE" not in types_of(
            "", "CREATE OPERATOR === (LEFTARG = INT, RIGHTARG = INT, FUNCTION = int4eq);"
        )


class TestAlterTableInTheSchemaTree:
    """A tree may append ``ALTER TABLE`` rather than edit the ``CREATE TABLE``.

    This went into the #288 sweep as a *control* — the most ordinary schema
    change there is — and came back invisible: ``_collect_alter_table_constraints``
    read only ``Constraint`` nodes out of ``stmt.cmds``, so a ``ColumnDef`` was
    dropped on the floor and a project written this way had no column gate at all.
    """

    def test_a_column_added_by_alter_is_reported(self):
        changes = changes_of("", "ALTER TABLE tb_user ADD COLUMN email TEXT;")
        assert [(c.type, c.table, c.column) for c in changes] == [
            ("ADD_COLUMN", "tb_user", "email")
        ]

    def test_a_column_dropped_by_alter_is_reported(self):
        assert [
            (c.type, c.column) for c in changes_of("", "ALTER TABLE tb_user DROP COLUMN name;")
        ] == [("DROP_COLUMN", "name")]

    def test_a_column_added_by_alter_on_both_sides_is_not_a_change(self):
        alter = "ALTER TABLE tb_user ADD COLUMN email TEXT;"
        assert types_of(alter, alter) == []

    def test_a_column_moved_from_alter_into_the_create_is_not_a_change(self):
        """The tree's *result* is what a database gets, not how it was written."""
        assert (
            SchemaDiffer()
            .compare(
                BASE + "ALTER TABLE tb_user ADD COLUMN email TEXT;",
                "CREATE TABLE tb_user (pk_user BIGINT PRIMARY KEY, name TEXT, email TEXT);\n",
            )
            .changes
            == []
        )

    def test_alter_on_a_table_the_tree_never_creates_is_not_a_crash(self):
        assert types_of("", "ALTER TABLE tb_absent ADD COLUMN email TEXT;") == []

    def test_a_column_type_changed_by_alter_is_reported(self):
        assert "CHANGE_COLUMN_TYPE" in types_of(
            "", "ALTER TABLE tb_user ALTER COLUMN name TYPE VARCHAR(50);"
        )


class TestTypesAndDomains:
    def test_added_domain_is_reported(self):
        assert "ADD_DOMAIN" in types_of(
            "", "CREATE DOMAIN d_email AS TEXT CHECK (VALUE LIKE '%@%');"
        )

    def test_redefined_domain_is_reported(self):
        assert "REPLACE_DOMAIN" in types_of(
            "CREATE DOMAIN d_email AS TEXT CHECK (VALUE LIKE '%@%');",
            "CREATE DOMAIN d_email AS TEXT CHECK (VALUE LIKE '%@%.%');",
        )

    def test_added_composite_type_is_reported(self):
        assert "ADD_TYPE" in types_of("", "CREATE TYPE t_point AS (x INT, y INT);")

    def test_redefined_composite_type_is_reported(self):
        assert "REPLACE_TYPE" in types_of(
            "CREATE TYPE t_point AS (x INT, y INT);",
            "CREATE TYPE t_point AS (x INT, y INT, z INT);",
        )

    def test_an_enum_is_reported_once_as_an_enum(self):
        """``CreateEnumStmt`` is inventory kind ``type`` too; it must not double-report."""
        assert types_of("", "CREATE TYPE e_status AS ENUM ('a', 'b');") == ["ADD_ENUM_TYPE"]

    def test_a_changed_enum_is_still_a_changed_enum(self):
        assert types_of(
            "CREATE TYPE e_status AS ENUM ('a');", "CREATE TYPE e_status AS ENUM ('a', 'b');"
        ) == ["CHANGE_ENUM_VALUES"]


class TestTheKindsNothingElseModelled:
    """Triggers, policies, extensions, schemas — each one a migrate-only
    environment never receives if the tree gains it and no migration carries it."""

    TRIGGER = (
        "CREATE TRIGGER trg_touch BEFORE UPDATE ON tb_user "
        "FOR EACH ROW EXECUTE FUNCTION fn_touch();"
    )

    def test_added_trigger_is_reported(self):
        assert "ADD_TRIGGER" in types_of("", self.TRIGGER)

    def test_dropped_trigger_is_reported(self):
        assert "DROP_TRIGGER" in types_of(self.TRIGGER, "")

    def test_a_trigger_is_named_per_table(self):
        """Two tables may each have a ``trg_touch``; they are two objects."""
        other = (
            "CREATE TABLE tb_other (pk BIGINT);\n"
            "CREATE TRIGGER trg_touch BEFORE UPDATE ON tb_other "
            "FOR EACH ROW EXECUTE FUNCTION fn_touch();"
        )
        types = types_of(self.TRIGGER, self.TRIGGER + "\n" + other)
        assert types.count("ADD_TRIGGER") == 1
        assert "DROP_TRIGGER" not in types

    def test_a_retargeted_trigger_is_a_drop_and_an_add_not_a_replace(self):
        moved = self.TRIGGER.replace("ON tb_user", "ON tb_other")
        types = sorted(
            types_of(
                "CREATE TABLE tb_other (pk BIGINT);\n" + self.TRIGGER,
                "CREATE TABLE tb_other (pk BIGINT);\n" + moved,
            )
        )
        assert types == ["ADD_TRIGGER", "DROP_TRIGGER"]

    def test_added_policy_is_reported(self):
        assert "ADD_POLICY" in types_of("", "CREATE POLICY p_own ON tb_user USING (true);")

    def test_redefined_policy_is_reported(self):
        assert "REPLACE_POLICY" in types_of(
            "CREATE POLICY p_own ON tb_user USING (true);",
            "CREATE POLICY p_own ON tb_user USING (pk_user > 0);",
        )

    def test_added_extension_is_reported(self):
        """A migrate-only environment without the extension fails at first use."""
        assert "ADD_EXTENSION" in types_of("", "CREATE EXTENSION pgcrypto;")

    def test_if_not_exists_does_not_make_an_extension_a_different_object(self):
        assert (
            types_of("CREATE EXTENSION pgcrypto;", "CREATE EXTENSION IF NOT EXISTS pgcrypto;") == []
        )

    def test_added_schema_is_reported(self):
        assert "ADD_SCHEMA" in types_of("", "CREATE SCHEMA app;")

    def test_added_rule_is_reported(self):
        assert "ADD_RULE" in types_of(
            "", "CREATE RULE r_noop AS ON DELETE TO tb_user DO INSTEAD NOTHING;"
        )

    def test_added_event_trigger_is_reported(self):
        assert "ADD_EVENT_TRIGGER" in types_of(
            "", "CREATE EVENT TRIGGER et ON ddl_command_start EXECUTE FUNCTION fn_t();"
        )

    def test_added_range_type_is_reported(self):
        assert "ADD_TYPE" in types_of("", "CREATE TYPE tr_span AS RANGE (subtype = INT);")

    def test_added_statistics_is_reported(self):
        assert "ADD_STATISTICS" in types_of(
            "", "CREATE STATISTICS st ON pk_user, name FROM tb_user;"
        )

    def test_added_foreign_table_is_reported(self):
        assert "ADD_FOREIGN_TABLE" in types_of("", "CREATE FOREIGN TABLE ft (a INT) SERVER srv;")

    def test_added_server_is_reported(self):
        assert "ADD_SERVER" in types_of("", "CREATE SERVER srv FOREIGN DATA WRAPPER fdw;")

    def test_a_declined_statement_is_still_not_reported(self):
        """A role is cluster-scoped; `build` does not create one either."""
        assert types_of("", "CREATE ROLE app_reader;") == []
