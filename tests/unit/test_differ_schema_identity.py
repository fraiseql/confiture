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


class TestCompareKeysOnIdentity:
    """The comparison pairs each table with the same table, and with nothing else."""

    def test_a_column_added_to_the_first_of_two_colliding_tables(self) -> None:
        old = "CREATE TABLE tenant.tb_meter (id INT);\nCREATE TABLE etl.tb_meter (id INT);"
        new = (
            "CREATE TABLE tenant.tb_meter (id INT, added_column TEXT);\n"
            "CREATE TABLE etl.tb_meter (id INT);"
        )
        assert [str(c) for c in SchemaDiffer().compare(old, new).changes] == [
            "ADD COLUMN tenant.tb_meter.added_column"
        ]

    def test_swapping_build_order_changes_nothing(self) -> None:
        """The destructive direction: a file rename is not a schema change."""
        old = "CREATE TABLE tenant.t (id INT, a TEXT);\nCREATE TABLE etl.t (id INT, b TEXT);"
        new = "CREATE TABLE etl.t (id INT, b TEXT);\nCREATE TABLE tenant.t (id INT, a TEXT);"
        assert SchemaDiffer().compare(old, new).changes == []

    def test_a_table_added_in_a_second_schema_is_an_added_table(self) -> None:
        old = "CREATE TABLE tenant.t (id INT);"
        new = "CREATE TABLE tenant.t (id INT);\nCREATE TABLE etl.t (id INT, x TEXT);"
        assert [str(c) for c in SchemaDiffer().compare(old, new).changes] == ["ADD TABLE etl.t"]

    def test_dropping_one_of_two_colliding_tables_is_a_dropped_table(self) -> None:
        old = "CREATE TABLE tenant.t (id INT);\nCREATE TABLE etl.t (id INT);"
        new = "CREATE TABLE tenant.t (id INT);"
        assert [str(c) for c in SchemaDiffer().compare(old, new).changes] == ["DROP TABLE etl.t"]

    def test_the_default_schema_folds(self) -> None:
        """Trap T4: ``t`` and ``public.t`` are one table, and nothing is reported."""
        assert (
            SchemaDiffer()
            .compare("CREATE TABLE t (id INT);", "CREATE TABLE public.t (id INT);")
            .changes
            == []
        )

    def test_an_unqualified_change_prints_an_unqualified_name(self) -> None:
        """Trap T4: what confiture has always printed, for the schemas it has always read."""
        assert [
            str(c)
            for c in SchemaDiffer()
            .compare("CREATE TABLE tb_post (id INT);", "CREATE TABLE tb_post (id INT, b TEXT);")
            .changes
        ] == ["ADD COLUMN tb_post.b"]


class TestRenamesStayInsideOneSchema:
    """A cross-schema pairing is not a rename — ``RENAME TO`` cannot express one."""

    def test_a_table_moving_between_schemas_is_a_drop_and_an_add(self) -> None:
        old = "CREATE TABLE etl.tb_meter (id INT);"
        new = "CREATE TABLE tenant.tb_meter (id INT);"
        assert sorted(str(c) for c in SchemaDiffer().compare(old, new).changes) == [
            "ADD TABLE tenant.tb_meter",
            "DROP TABLE etl.tb_meter",
        ]

    def test_a_rename_inside_one_schema_is_still_a_rename(self) -> None:
        """The control that fails if the fix is "stop detecting renames"."""
        old = "CREATE TABLE tenant.tb_a (id INT);"
        new = "CREATE TABLE tenant.tb_b (id INT);"
        (change,) = SchemaDiffer().compare(old, new).changes
        assert change.type == "RENAME_TABLE"
        assert (change.old_value, change.new_value) == ("tenant.tb_a", "tenant.tb_b")
        assert change.details == {"old_name": "tb_a", "new_name": "tb_b"}

    def test_an_unqualified_rename_is_unchanged(self) -> None:
        (change,) = (
            SchemaDiffer()
            .compare("CREATE TABLE tb_a (id INT);", "CREATE TABLE tb_b (id INT);")
            .changes
        )
        assert (change.type, change.old_value, change.new_value) == (
            "RENAME_TABLE",
            "tb_a",
            "tb_b",
        )

    def test_the_fuzzy_matcher_cannot_separate_these_two_pairs(self) -> None:
        """Why the separation is grammatical: the scores are identical."""
        differ = SchemaDiffer()
        assert differ._similarity_score("tenant.tb_meter", "etl.tb_meter") == 0.6
        assert differ._similarity_score("tenant.tb_a", "tenant.tb_b") == 0.6


class TestEnumsAndSequencesUseTheSchemaTheyCarry:
    """``EnumType.schema`` and ``Sequence.schema`` have always existed and were ignored."""

    def test_a_value_added_to_one_of_two_colliding_enums(self) -> None:
        old = "CREATE TYPE a.status AS ENUM ('x'); CREATE TYPE b.status AS ENUM ('p','q');"
        new = "CREATE TYPE a.status AS ENUM ('x','y'); CREATE TYPE b.status AS ENUM ('p','q');"
        (change,) = SchemaDiffer().compare(old, new).changes
        assert str(change) == "CHANGE ENUM VALUES a.status"
        assert change.details == {"added_values": ["y"], "removed_values": []}

    def test_one_of_two_colliding_sequences_dropped(self) -> None:
        assert [
            str(c)
            for c in SchemaDiffer()
            .compare("CREATE SEQUENCE a.s1; CREATE SEQUENCE b.s1;", "CREATE SEQUENCE a.s1;")
            .changes
        ] == ["DROP SEQUENCE b.s1"]

    def test_an_unqualified_enum_prints_unqualified(self) -> None:
        assert [
            str(c) for c in SchemaDiffer().compare("", "CREATE TYPE mood AS ENUM ('ok');").changes
        ] == ["ADD ENUM TYPE mood"]

    def test_an_unqualified_sequence_folds_against_public(self) -> None:
        assert (
            SchemaDiffer().compare("CREATE SEQUENCE s;", "CREATE SEQUENCE public.s;").changes == []
        )


class TestTheRepositorysOwnExample:
    """``examples/06-prep-seed-validation`` ships two ``tb_manufacturer`` tables.

    The prep-seed pattern *is* two schemas holding the same table names —
    confiture's own documented idiom — and the differ could not see it. Pinned
    against the shipped example rather than a synthetic string, so a regression
    shows up against something a user actually runs.
    """

    @staticmethod
    def _schema_sql() -> str:
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "examples/06-prep-seed-validation/db/schema"
        return "\n".join(path.read_text() for path in sorted(root.rglob("*.sql")))

    def test_the_example_declares_two_tables_of_one_name(self) -> None:
        """If the example's files move, fail here rather than silently read nothing."""
        tables = SchemaDiffer().parse_schema(self._schema_sql()).tables
        assert sorted(t.qualified for t in tables if t.name == "tb_manufacturer") == [
            "catalog.tb_manufacturer",
            "prep_seed.tb_manufacturer",
        ]

    def test_a_column_added_to_the_catalog_table_is_reported(self) -> None:
        old = self._schema_sql()
        new = old.replace(
            "CREATE TABLE catalog.tb_manufacturer (",
            "CREATE TABLE catalog.tb_manufacturer (\n    added_column TEXT,",
            1,
        )
        assert [str(c) for c in SchemaDiffer().compare(old, new).changes] == [
            "ADD COLUMN catalog.tb_manufacturer.added_column"
        ]
