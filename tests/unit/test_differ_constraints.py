"""A constraint written in DDL reaches the diff whole (#315, #316).

Three places in PostgreSQL's grammar carry a ``Constraint`` node — on a column,
at table level inside ``CREATE TABLE``, and in ``ALTER TABLE … ADD CONSTRAINT``.
``core/differ.py`` read them with three different pieces of code, and each
divergence reached either what ``migrate diff`` reports or the DDL it generates:
the column loop read no constraint at all, and the two that did read one
disagreed about what a CHECK expression is.

The assertions here are that the *same* constraint, however it is spelled,
produces the *same* model.
"""

from __future__ import annotations

from confiture.core.differ import SchemaDiffer
from confiture.core.schema_model import Table

PARENT = "CREATE TABLE b.parent (id INT PRIMARY KEY);\n"


def _table(sql: str, index: int = -1) -> Table:
    return SchemaDiffer().parse_schema(sql).tables[index]


class TestAColumnLevelConstraintIsATableConstraint:
    """#315: ``_parse_column_pglast`` returns a ``Column``, which has nowhere to
    put a foreign key — so a FK written on the column was read by nobody."""

    def test_a_column_level_reference_is_a_foreign_key(self) -> None:
        table = _table(PARENT + "CREATE TABLE a.child (pid INT REFERENCES b.parent(id));")
        assert len(table.constraints_of("foreign_key")) == 1
        fk = table.constraints_of("foreign_key")[0]
        assert (table.qualified, fk.columns, fk.ref_table, fk.ref_columns) == (
            "a.child",
            ("pid",),
            "b.parent",
            ("id",),
        )

    def test_the_two_spellings_of_one_foreign_key_agree(self) -> None:
        column_level = _table(
            PARENT + "CREATE TABLE a.child (pid INT CONSTRAINT fk_c REFERENCES b.parent(id));"
        )
        table_level = _table(
            PARENT + "CREATE TABLE a.child (pid INT,"
            " CONSTRAINT fk_c FOREIGN KEY (pid) REFERENCES b.parent(id));"
        )
        assert column_level.constraints_of("foreign_key") == table_level.constraints_of(
            "foreign_key"
        )

    def test_an_unnamed_constraint_keeps_no_name(self) -> None:
        """PostgreSQL generates ``child_pid_fkey`` at apply time. It is not
        confiture's to write, here or in generated DDL."""
        table = _table(PARENT + "CREATE TABLE a.child (pid INT REFERENCES b.parent(id));")
        assert table.constraints_of("foreign_key")[0].name == ""

    def test_a_reference_with_no_column_list_is_still_a_foreign_key(self) -> None:
        """``REFERENCES b.parent`` means the parent's primary key."""
        table = _table(PARENT + "CREATE TABLE a.child (pid INT REFERENCES b.parent);")
        assert len(table.constraints_of("foreign_key")) == 1
        assert table.constraints_of("foreign_key")[0].ref_columns == ()

    def test_a_column_level_unique_is_a_unique_constraint(self) -> None:
        table = _table("CREATE TABLE tenant.t (u INT UNIQUE);")
        assert len(table.constraints_of("unique")) == 1
        assert (table.qualified, table.constraints_of("unique")[0].columns) == ("tenant.t", ("u",))

    def test_a_column_level_check_is_a_check_constraint(self) -> None:
        table = _table("CREATE TABLE tenant.t (c INT CHECK (c > 0));")
        assert len(table.constraints_of("check")) == 1
        assert table.qualified == "tenant.t"

    def test_two_unnamed_column_level_foreign_keys_are_two_foreign_keys(self) -> None:
        """Both are unnamed, so a model keyed by name would keep one."""
        table = _table(
            PARENT + "CREATE TABLE a.child (a INT REFERENCES b.parent(id),"
            " z INT REFERENCES b.parent(id));"
        )
        assert [fk.columns for fk in table.constraints_of("foreign_key")] == [("a",), ("z",)]

    def test_a_generated_column_is_not_a_check_constraint(self) -> None:
        """``CONSTR_GENERATED`` carries a ``raw_expr`` too, and it is not a CHECK.

        Reading ``raw_expr`` by its presence rather than by the constraint's kind
        would turn every generated column into a CHECK constraint.
        """
        table = _table("CREATE TABLE tenant.t (c INT, g INT GENERATED ALWAYS AS (c * 2) STORED);")
        assert table.constraints_of("check") == ()


class TestOneCheckConstraintHasOneExpression:
    """#316: one reader stored ``RawStream()(raw_expr)``, the other the AST class
    name. Unifying them is what settles which is right."""

    def test_a_check_expression_is_the_expression(self) -> None:
        table = _table("CREATE TABLE tenant.t (id INT, CONSTRAINT ck CHECK (id > 0));")
        assert table.constraints_of("check")[0].expression == "id > 0"

    def test_the_two_spellings_of_one_check_agree(self) -> None:
        in_create = _table("CREATE TABLE tenant.t (id INT, CONSTRAINT ck CHECK (id > 0));")
        in_alter = _table(
            "CREATE TABLE tenant.t (id INT);\n"
            "ALTER TABLE tenant.t ADD CONSTRAINT ck CHECK (id > 0);"
        )
        assert in_create.constraints_of("check") == in_alter.constraints_of("check")


class TestReferentialActionsSurvive:
    """A generated FK that silently stops cascading applies cleanly and is wrong."""

    def test_on_delete_and_on_update_are_read_from_the_column_form(self) -> None:
        table = _table(
            PARENT + "CREATE TABLE a.child (pid INT REFERENCES b.parent(id)"
            " ON DELETE CASCADE ON UPDATE RESTRICT);"
        )
        fk = table.constraints_of("foreign_key")[0]
        assert (fk.on_delete, fk.on_update) == ("CASCADE", "RESTRICT")

    def test_on_delete_and_on_update_are_read_from_the_table_form(self) -> None:
        table = _table(
            PARENT + "CREATE TABLE a.child (pid INT, CONSTRAINT fk_c FOREIGN KEY (pid)"
            " REFERENCES b.parent(id) ON DELETE SET NULL ON UPDATE CASCADE);"
        )
        fk = table.constraints_of("foreign_key")[0]
        assert (fk.on_delete, fk.on_update) == ("SET NULL", "CASCADE")

    def test_on_delete_and_on_update_are_read_from_the_alter_form(self) -> None:
        table = _table(
            PARENT + "CREATE TABLE a.child (pid INT);\n"
            "ALTER TABLE a.child ADD CONSTRAINT fk_c FOREIGN KEY (pid)"
            " REFERENCES b.parent(id) ON DELETE CASCADE ON UPDATE SET DEFAULT;"
        )
        fk = table.constraints_of("foreign_key")[0]
        assert (fk.on_delete, fk.on_update) == ("CASCADE", "SET DEFAULT")

    def test_no_action_is_reported_as_no_clause(self) -> None:
        """``NO ACTION`` is PostgreSQL's default; generated DDL writes no clause."""
        table = _table(PARENT + "CREATE TABLE a.child (pid INT REFERENCES b.parent(id));")
        fk = table.constraints_of("foreign_key")[0]
        assert (fk.on_delete, fk.on_update) == (None, None)


class TestTableLevelPrimaryKeyReachesItsColumns:
    """``PRIMARY KEY (id)`` and ``id INT PRIMARY KEY`` are one declaration."""

    def test_the_two_spellings_produce_the_same_columns(self) -> None:
        assert (
            _table("CREATE TABLE t (id INT, PRIMARY KEY (id));").columns
            == _table("CREATE TABLE t (id INT PRIMARY KEY);").columns
        )

    def test_respelling_a_primary_key_is_not_a_change(self) -> None:
        """It generated ``ALTER COLUMN id DROP NOT NULL``, which PostgreSQL
        refuses on a primary-key column — a failing migration from a no-op."""
        diff = SchemaDiffer().compare(
            "CREATE TABLE t (id INT PRIMARY KEY);",
            "CREATE TABLE t (id INT, PRIMARY KEY (id));",
        )
        assert diff.changes == []

    def test_a_composite_primary_key_marks_every_column(self) -> None:
        table = _table("CREATE TABLE t (a INT, b INT, c INT, PRIMARY KEY (a, b));")
        assert [(c.name, c.primary_key, c.not_null) for c in table.columns] == [
            ("a", True, True),
            ("b", True, True),
            ("c", False, False),
        ]


class TestAnAddedColumnBringsItsConstraints:
    """``ALTER TABLE … ADD COLUMN`` carries the same clauses a ``CREATE TABLE``
    column does, and reaches the schema through the same reader."""

    def test_an_added_column_keeps_not_null_and_its_default(self) -> None:
        table = _table(
            "CREATE TABLE t (id INT);\nALTER TABLE t ADD COLUMN x INT NOT NULL DEFAULT 5;"
        )
        added = table.column("x")
        assert added is not None
        assert (added.not_null, added.default) == (True, "5")

    def test_an_added_column_brings_its_foreign_key(self) -> None:
        table = _table(
            PARENT + "CREATE TABLE a.child (id INT);\n"
            "ALTER TABLE a.child ADD COLUMN pid INT REFERENCES b.parent(id);"
        )
        assert [(fk.columns, fk.ref_table) for fk in table.constraints_of("foreign_key")] == [
            (("pid",), "b.parent")
        ]

    def test_an_added_column_can_be_the_primary_key(self) -> None:
        table = _table("CREATE TABLE t (a INT);\nALTER TABLE t ADD COLUMN pk INT PRIMARY KEY;")
        added = table.column("pk")
        assert added is not None
        assert (added.primary_key, added.not_null) == (True, True)


class TestAnUnnamedConstraintIsIdentifiedByWhatItSays:
    """``{fk.name: fk}`` cannot tell two unnamed constraints apart.

    #313's defect one field along: a dict key that cannot express the identity.
    A named constraint is identified by its name; an unnamed one by its content,
    which is the only thing that distinguishes it. Nothing invents a name — the
    identity is internal, and generated DDL still writes no ``CONSTRAINT`` clause.
    """

    def test_two_unnamed_foreign_keys_are_two_changes(self) -> None:
        old = "CREATE TABLE b.p (id INT PRIMARY KEY);\nCREATE TABLE t (a INT, z INT);"
        new = (
            "CREATE TABLE b.p (id INT PRIMARY KEY);\n"
            "CREATE TABLE t (a INT REFERENCES b.p(id), z INT REFERENCES b.p(id));"
        )
        added = [c for c in SchemaDiffer().compare(old, new).wire() if c.type == "ADD_FOREIGN_KEY"]
        assert sorted((c.details or {})["columns"][0] for c in added) == ["a", "z"]

    def test_two_unnamed_unique_constraints_are_two_changes(self) -> None:
        old = "CREATE TABLE t (a INT, z INT);"
        new = "CREATE TABLE t (a INT UNIQUE, z INT UNIQUE);"
        added = [
            c for c in SchemaDiffer().compare(old, new).wire() if c.type == "ADD_UNIQUE_CONSTRAINT"
        ]
        assert sorted((c.details or {})["columns"][0] for c in added) == ["a", "z"]

    def test_two_unnamed_check_constraints_are_two_changes(self) -> None:
        old = "CREATE TABLE t (a INT, z INT);"
        new = "CREATE TABLE t (a INT CHECK (a > 0), z INT CHECK (z > 0));"
        added = [
            c for c in SchemaDiffer().compare(old, new).wire() if c.type == "ADD_CHECK_CONSTRAINT"
        ]
        assert sorted((c.details or {})["expression"] for c in added) == ["a > 0", "z > 0"]

    def test_two_unnamed_indexes_are_two_changes(self) -> None:
        old = "CREATE TABLE t (a INT, z INT);"
        new = "CREATE TABLE t (a INT, z INT);\nCREATE INDEX ON t (a);\nCREATE INDEX ON t (z);"
        added = [c for c in SchemaDiffer().compare(old, new).wire() if c.type == "ADD_INDEX"]
        assert sorted((c.details or {})["columns"][0] for c in added) == ["a", "z"]


class TestACheckThatChangedIsAChange:
    """#316: only a CHECK's *presence* was compared, because its expression was
    stored as the AST class name and every expression was therefore ``A_Expr``."""

    def test_a_changed_expression_reports_a_drop_and_an_add_in_that_order(self) -> None:
        diff = SchemaDiffer().compare(
            "CREATE TABLE tenant.t (id INT, CONSTRAINT ck CHECK (id > 0));",
            "CREATE TABLE tenant.t (id INT, CONSTRAINT ck CHECK (id > 5));",
        )
        wire = diff.wire()
        assert [c.type for c in wire] == [
            "DROP_CHECK_CONSTRAINT",
            "ADD_CHECK_CONSTRAINT",
        ]
        assert (wire[0].details or {})["expression"] == "id > 0"
        assert (wire[1].details or {})["expression"] == "id > 5"

    def test_respelling_one_predicate_is_not_a_change(self) -> None:
        """The expression comes from the parser, so whitespace and redundant
        parentheses are not a schema change."""
        diff = SchemaDiffer().compare(
            "CREATE TABLE t (id INT, CONSTRAINT ck CHECK (id>0));",
            "CREATE TABLE t (id INT, CONSTRAINT ck CHECK ( (id > 0) ));",
        )
        assert diff.changes == []

    def test_a_foreign_key_respelled_is_not_reported(self) -> None:
        """A deliberate limit, recorded rather than left to be discovered.

        ``REFERENCES b.p`` and ``REFERENCES b.p(id)`` are the same constraint when
        ``id`` is the parent's primary key, and deciding that means resolving the
        referenced key. Reporting the difference would generate a
        ``DROP CONSTRAINT`` for a constraint that did not change, which is worse
        than staying quiet. A CHECK has no such ambiguity: one predicate has one
        rendering.
        """
        diff = SchemaDiffer().compare(
            "CREATE TABLE b.p (id INT PRIMARY KEY);\n"
            "CREATE TABLE t (pid INT, CONSTRAINT fk FOREIGN KEY (pid) REFERENCES b.p(id));",
            "CREATE TABLE b.p (id INT PRIMARY KEY);\n"
            "CREATE TABLE t (pid INT, CONSTRAINT fk FOREIGN KEY (pid) REFERENCES b.p);",
        )
        assert diff.changes == []
