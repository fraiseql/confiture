"""The diff sees every difference drift sees — the engine drift is about to render.

``confiture drift`` compared a primary key, a foreign key's actions, a UNIQUE's
columns under one name, every unnamed CHECK, a default's value and a TVIEW's pinned
options; the differ compared none of them, so ``migrate diff --from db`` generated
no migration for a database drift reported broken, and a primary key added with
its column was written as ``ADD COLUMN id INTEGER NOT NULL`` — the key lost. Each
test here is one of those, on both policies where both apply.
"""

from dataclasses import replace

from confiture.core.differ import SchemaDiffer, Side
from confiture.core.schema_change import (
    CheckConstraintAdded,
    ColumnAdded,
    ColumnDefaultChanged,
    ForeignKeyAdded,
    ForeignKeyDropped,
    ObjectReplaced,
    PrimaryKeyAdded,
    PrimaryKeyDropped,
    SchemaChange,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)
from confiture.core.schema_model import Table, TView, tview_ref
from confiture.core.schema_read import read_text


def kinds(changes: list[SchemaChange]) -> list[str]:
    return [type(change).__name__ for change in changes]


def tree(sql: str) -> Side:
    return Side.of(read_text(sql))


def database(sql: str, **renamed: str) -> Side:
    """*sql* as a database holds it once applied: every constraint named, as PostgreSQL names it.

    *renamed* maps a constraint's kind to the name PostgreSQL gave it.
    """
    model = read_text(sql).catalogued

    def named(table: Table) -> Table:
        return replace(
            table,
            constraints=tuple(
                replace(c, name=c.name or renamed.get(c.kind, f"{table.name}_{c.kind}"))
                for c in table.constraints
            ),
        )

    tables = {ref: named(table) for ref, table in model.tables.items()}
    return Side(replace(model, tables=tables, source="catalog"))


def diff(old: Side, new: Side) -> list[SchemaChange]:
    return SchemaDiffer().compare_sides(old, new).changes


class TestAPrimaryKey:
    def test_one_added_to_a_table_is_a_change(self) -> None:
        changes = diff(
            tree("CREATE TABLE t (id INT NOT NULL);"),
            tree("CREATE TABLE t (id INT PRIMARY KEY);"),
        )
        assert kinds(changes) == ["PrimaryKeyAdded"]

    def test_one_added_with_its_column_is_not_lost(self) -> None:
        changes = diff(
            tree("CREATE TABLE t (b INT);"), tree("CREATE TABLE t (b INT, id INT PRIMARY KEY);")
        )
        assert kinds(changes) == ["ColumnAdded", "PrimaryKeyAdded"]
        assert isinstance(changes[0], ColumnAdded)
        assert isinstance(changes[1], PrimaryKeyAdded)
        assert changes[1].constraint.columns == ("id",)

    def test_one_re_keyed_under_its_name_is_a_drop_and_an_add(self) -> None:
        changes = diff(
            tree("CREATE TABLE t (a INT NOT NULL, b INT NOT NULL, CONSTRAINT pk PRIMARY KEY (a));"),
            tree(
                "CREATE TABLE t (a INT NOT NULL, b INT NOT NULL, CONSTRAINT pk PRIMARY KEY (a, b));"
            ),
        )
        assert kinds(changes) == ["PrimaryKeyDropped", "PrimaryKeyAdded"]

    def test_one_a_database_lost_is_a_change(self) -> None:
        live = database("CREATE TABLE t (id INT NOT NULL);")
        changes = diff(live, tree("CREATE TABLE t (id INT PRIMARY KEY);"))
        assert kinds(changes) == ["PrimaryKeyAdded"]

    def test_one_a_renamed_table_still_holds_under_its_old_name_is_no_change(self) -> None:
        """``ALTER TABLE … RENAME TO`` keeps ``old_pkey``: no name of PostgreSQL's shape."""
        live = database("CREATE TABLE after (id INT PRIMARY KEY);", primary_key="before_pkey")
        assert diff(live, tree("CREATE TABLE after (id INT PRIMARY KEY);")) == []

    def test_one_dropped_in_a_database_is_a_drop_the_other_way(self) -> None:
        live = database("CREATE TABLE t (id INT PRIMARY KEY);")
        changes = diff(tree("CREATE TABLE t (id INT NOT NULL);"), live)
        assert kinds(changes) == ["PrimaryKeyAdded"]
        changes = diff(live, tree("CREATE TABLE t (id INT NOT NULL);"))
        assert kinds(changes) == ["PrimaryKeyDropped"]
        assert isinstance(changes[0], PrimaryKeyDropped)
        assert changes[0].constraint.name == "t_primary_key"


PARENT = "CREATE TABLE p (id INT PRIMARY KEY);"


class TestAForeignKeyUnderOneName:
    def test_that_loses_its_action_is_a_drop_and_an_add(self) -> None:
        changes = diff(
            tree(f"{PARENT} CREATE TABLE c (pid INT, CONSTRAINT f FOREIGN KEY (pid) "
                 "REFERENCES p (id) ON DELETE CASCADE);"),
            tree(f"{PARENT} CREATE TABLE c (pid INT, CONSTRAINT f FOREIGN KEY (pid) "
                 "REFERENCES p (id));"),
        )  # fmt: skip
        assert kinds(changes) == ["ForeignKeyDropped", "ForeignKeyAdded"]
        assert isinstance(changes[0], ForeignKeyDropped)
        assert isinstance(changes[1], ForeignKeyAdded)
        assert (changes[0].constraint.on_delete, changes[1].constraint.on_delete) == (
            "CASCADE",
            None,
        )

    def test_that_is_re_pointed_is_a_drop_and_an_add(self) -> None:
        changes = diff(
            tree(f"{PARENT} CREATE TABLE q (id INT PRIMARY KEY); "
                 "CREATE TABLE c (pid INT, CONSTRAINT f FOREIGN KEY (pid) REFERENCES p);"),
            tree(f"{PARENT} CREATE TABLE q (id INT PRIMARY KEY); "
                 "CREATE TABLE c (pid INT, CONSTRAINT f FOREIGN KEY (pid) REFERENCES q);"),
        )  # fmt: skip
        assert kinds(changes) == ["ForeignKeyDropped", "ForeignKeyAdded"]

    def test_whose_referenced_key_is_written_on_one_side_only_is_no_change(self) -> None:
        assert (
            diff(
                tree(
                    f"{PARENT} CREATE TABLE c (pid INT, CONSTRAINT f FOREIGN KEY (pid) "
                    "REFERENCES p);"
                ),
                tree(
                    f"{PARENT} CREATE TABLE c (pid INT, CONSTRAINT f FOREIGN KEY (pid) "
                    "REFERENCES p (id));"
                ),
            )
            == []
        )


def test_a_unique_that_gains_a_column_under_its_name_is_a_drop_and_an_add() -> None:
    changes = diff(
        tree("CREATE TABLE t (a INT, b INT, CONSTRAINT u UNIQUE (a));"),
        tree("CREATE TABLE t (a INT, b INT, CONSTRAINT u UNIQUE (a, b));"),
    )
    assert kinds(changes) == ["UniqueConstraintDropped", "UniqueConstraintAdded"]
    assert isinstance(changes[0], UniqueConstraintDropped)
    assert isinstance(changes[1], UniqueConstraintAdded)


class TestUnnamedChecksAgainstADatabase:
    """PostgreSQL stores a CHECK analysed, so each one says ``<expression>``: none collapses."""

    TWO = "CREATE TABLE t (a INT CHECK (a > 0), b INT CHECK (b > 0));"

    def test_two_the_database_holds_are_no_change(self) -> None:
        assert diff(database(self.TWO), tree(self.TWO)) == []

    def test_one_the_database_lost_is_one_added(self) -> None:
        live = database("CREATE TABLE t (a INT CHECK (a > 0), b INT);", check="t_a_check")
        changes = diff(live, tree(self.TWO))
        assert kinds(changes) == ["CheckConstraintAdded"]
        assert isinstance(changes[0], CheckConstraintAdded)


class TestADefaultAgainstADatabase:
    def test_another_value_is_a_change(self) -> None:
        live = database("CREATE TABLE t (s TEXT DEFAULT 'a'::text);")
        changes = diff(live, tree("CREATE TABLE t (s TEXT DEFAULT 'b');"))
        assert kinds(changes) == ["ColumnDefaultChanged"]
        assert isinstance(changes[0], ColumnDefaultChanged)
        assert changes[0].new == "'b'"

    def test_the_value_stored_analysed_is_no_change(self) -> None:
        live = database("CREATE TABLE t (s TEXT DEFAULT 'a'::text);")
        assert diff(live, tree("CREATE TABLE t (s TEXT DEFAULT 'a');")) == []

    def test_a_null_default_is_none(self) -> None:
        live = database("CREATE TABLE t (s TEXT);")
        assert diff(live, tree("CREATE TABLE t (s TEXT DEFAULT NULL);")) == []


def test_an_array_is_one_type_however_many_dimensions_it_was_declared_with() -> None:
    assert diff(tree("CREATE TABLE t (g INTEGER[][]);"), tree("CREATE TABLE t (g INT[]);")) == []
    live = database("CREATE TABLE t (g INTEGER[]);")
    assert diff(live, tree("CREATE TABLE t (g INTEGER[][]);")) == []


TVIEW_TREE = """
CREATE TABLE tb_post (pk_post bigint PRIMARY KEY);
CREATE TABLE tv_post AS SELECT pk_post FROM tb_post;
"""


class TestATviewsOptions:
    """Against a tree, an option it does not pin is pg_tviews' to choose (``tview_defaults``)."""

    @staticmethod
    def sides(pinned: str, **held: object) -> tuple[Side, Side]:
        """The database (holding *held*) and the tree (*pinned* appended to it)."""
        declared = read_text(TVIEW_TREE + pinned)
        live = read_text(TVIEW_TREE)
        tviews = {ref: replace(tview, **held) for ref, tview in live.catalogued.tviews.items()}
        model = replace(live.catalogued, tviews=tviews, source="catalog")
        return Side(model, live.declared.objects), Side.of(declared, held=True)

    def test_one_the_tree_does_not_pin_is_no_change(self) -> None:
        live, declared = self.sides("", logged=True, fillfactor=70)
        assert diff(live, declared) == []

    def test_one_the_tree_pins_is_a_change(self) -> None:
        live, declared = self.sides(
            "ALTER TABLE tv_post SET (fillfactor = 70);\n", logged=False, fillfactor=85
        )
        changes = diff(live, declared)
        assert kinds(changes) == ["ObjectReplaced"]
        assert isinstance(changes[0], ObjectReplaced)
        assert changes[0].ref == tview_ref(TView(name="tv_post"))

    def test_one_the_tree_pins_as_the_database_holds_it_is_no_change(self) -> None:
        live, declared = self.sides(
            "ALTER TABLE tv_post SET (fillfactor = 85);\n", logged=False, fillfactor=85
        )
        assert diff(live, declared) == []
