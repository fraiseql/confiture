"""The differ knows which schema a relation is in (#313).

Two tables of one name in two schemas are two tables. Every statement the
differ folds lands on the relation that statement names, and nothing else.

The controls matter as much as the cases: a tree that writes no schema must
behave exactly as it did before, because that is every schema confiture has
ever diffed.
"""

from confiture.core.differ import SchemaDiffer


def _identities(sql: str) -> list[tuple[str | None, str]]:
    return [(t.schema, t.name) for t in SchemaDiffer().parse_schema(sql).tables]


class TestTableCarriesItsSchema:
    """``CREATE TABLE tenant.t`` and ``CREATE TABLE etl.t`` are two tables."""

    def test_two_schemas_two_tables(self) -> None:
        assert _identities("CREATE TABLE tenant.t (id INT);\nCREATE TABLE etl.t (id INT);") == [
            ("tenant", "t"),
            ("etl", "t"),
        ]

    def test_unqualified_table_carries_no_schema(self) -> None:
        """What the author wrote, never an invented ``public.`` (trap T4)."""
        assert _identities("CREATE TABLE t (id INT);") == [(None, "t")]

    def test_tables_of_one_name_in_two_schemas_are_not_equal(self) -> None:
        tables = SchemaDiffer().parse_schema(
            "CREATE TABLE tenant.t (id INT);\nCREATE TABLE etl.t (id INT);"
        )
        assert tables.tables[0] != tables.tables[1]

    def test_qualified_prints_what_the_author_wrote(self) -> None:
        tenant, bare = (
            SchemaDiffer().parse_schema("CREATE TABLE tenant.t (id INT);\nCREATE TABLE u (id INT);")
        ).tables
        assert tenant.qualified == "tenant.t"
        assert bare.qualified == "u"


class TestAlterLandsOnTheTableItNames:
    """An ``ALTER`` or a ``CREATE INDEX`` reaches the relation it names."""

    def test_alter_add_column_lands_on_the_named_schema(self) -> None:
        tables = (
            SchemaDiffer()
            .parse_schema(
                "CREATE TABLE tenant.t (id INT);\n"
                "CREATE TABLE etl.t (id INT);\n"
                "ALTER TABLE etl.t ADD COLUMN only_in_etl TEXT;"
            )
            .tables
        )
        assert [(t.schema, [c.name for c in t.columns]) for t in tables] == [
            ("tenant", ["id"]),
            ("etl", ["id", "only_in_etl"]),
        ]

    def test_create_index_lands_on_the_named_schema(self) -> None:
        tables = (
            SchemaDiffer()
            .parse_schema(
                "CREATE TABLE tenant.t (id INT);\n"
                "CREATE TABLE etl.t (id INT);\n"
                "CREATE INDEX idx_etl ON etl.t (id);"
            )
            .tables
        )
        assert [(t.schema, [ix.name for ix in t.indexes]) for t in tables] == [
            ("tenant", []),
            ("etl", ["idx_etl"]),
        ]

    def test_an_alter_naming_no_schema_still_folds(self) -> None:
        """The wildcard ``ddl_objects._matches`` and ``inventory.find_all`` apply.

        A statement that wrote no schema did not say which one it meant.
        """
        tables = (
            SchemaDiffer()
            .parse_schema("CREATE TABLE public.t (id INT);\nALTER TABLE t ADD COLUMN b TEXT;")
            .tables
        )
        assert [c.name for c in tables[0].columns] == ["id", "b"]

    def test_an_alter_on_a_schema_the_tree_never_created_folds_nowhere(self) -> None:
        tables = (
            SchemaDiffer()
            .parse_schema("CREATE TABLE tenant.t (id INT);\nALTER TABLE other.t ADD COLUMN b TEXT;")
            .tables
        )
        assert [c.name for c in tables[0].columns] == ["id"]


class TestDropAndRenameReachOneTable:
    """A ``DROP`` or a ``RENAME`` naming a schema touches that schema only."""

    def test_drop_leaves_the_other_schema_standing(self) -> None:
        tables = (
            SchemaDiffer()
            .parse_schema(
                "CREATE TABLE tenant.t (id INT);\nCREATE TABLE etl.t (id INT);\nDROP TABLE etl.t;"
            )
            .tables
        )
        assert [(t.schema, t.name) for t in tables] == [("tenant", "t")]

    def test_rename_renames_one_table(self) -> None:
        tables = (
            SchemaDiffer()
            .parse_schema(
                "CREATE TABLE tenant.t (id INT);\n"
                "CREATE TABLE etl.t (id INT);\n"
                "ALTER TABLE etl.t RENAME TO t2;"
            )
            .tables
        )
        assert [(t.schema, t.name) for t in tables] == [("tenant", "t"), ("etl", "t2")]

    def test_rename_column_renames_on_one_table(self) -> None:
        tables = (
            SchemaDiffer()
            .parse_schema(
                "CREATE TABLE tenant.t (id INT);\n"
                "CREATE TABLE etl.t (id INT);\n"
                "ALTER TABLE etl.t RENAME COLUMN id TO ident;"
            )
            .tables
        )
        assert [(t.schema, [c.name for c in t.columns]) for t in tables] == [
            ("tenant", ["id"]),
            ("etl", ["ident"]),
        ]

    def test_a_drop_naming_no_schema_still_drops(self) -> None:
        assert (
            SchemaDiffer().parse_schema("CREATE TABLE tenant.t (id INT);\nDROP TABLE t;").tables
            == []
        )

    def test_drop_if_exists_before_create_still_declares_the_table(self) -> None:
        """The fold is order-aware and stays so (#301)."""
        tables = (
            SchemaDiffer()
            .parse_schema("DROP TABLE IF EXISTS tenant.x;\nCREATE TABLE tenant.x (id INT);")
            .tables
        )
        assert [(t.schema, t.name) for t in tables] == [("tenant", "x")]


class TestSetSchemaFolds:
    """``ALTER TABLE … SET SCHEMA`` moves the table, now that a table has one."""

    def test_set_schema_moves_the_table(self) -> None:
        tables = (
            SchemaDiffer()
            .parse_schema("CREATE TABLE a.t (id int);\nALTER TABLE a.t SET SCHEMA b;")
            .tables
        )
        assert [(t.schema, t.name) for t in tables] == [("b", "t")]

    def test_set_schema_moves_only_the_table_it_names(self) -> None:
        tables = (
            SchemaDiffer()
            .parse_schema(
                "CREATE TABLE a.t (id int);\nCREATE TABLE c.t (id int);\nALTER TABLE a.t SET SCHEMA b;"
            )
            .tables
        )
        assert [(t.schema, t.name) for t in tables] == [("b", "t"), ("c", "t")]
