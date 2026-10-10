"""A generated migration runs its changes in an order PostgreSQL accepts (#335).

The differ reports tables, then enum types and sequences, then the objects compared
by definition, each group by name. Applied in that order, a table is created before
the schema it lives in, the extension its default calls and the enum type its column
has, and before the tables its foreign keys reference.
"""

import pytest

from confiture.core.change_order import apply_order
from confiture.core.differ import SchemaDiffer
from confiture.core.schema_change import ForeignKeyAdded, SchemaChange, TableAdded


def _labels(changes: list[SchemaChange]) -> list[str]:
    labels = []
    for change in changes:
        wire = change.to_wire()
        labels.append(f"{wire.type} {wire.table}".strip())
    return labels


def _ordered(old: str, new: str) -> list[str]:
    return _labels(apply_order(SchemaDiffer().compare(old, new).changes))


def test_a_table_follows_the_tables_it_references() -> None:
    new = (
        "CREATE TABLE a_child (id INT, pid INT REFERENCES z_parent(id));\n"
        "CREATE TABLE z_parent (id INT PRIMARY KEY);\n"
    )
    assert _ordered("", new) == ["ADD_TABLE z_parent", "ADD_TABLE a_child"]


def test_namespaces_extensions_and_types_come_before_tables() -> None:
    new = (
        "CREATE TABLE app.t (id UUID DEFAULT uuid_generate_v4(), m mood, n INT"
        " DEFAULT nextval('s'));\n"
        'CREATE EXTENSION "uuid-ossp";\n'
        "CREATE SCHEMA app;\n"
        "CREATE TYPE mood AS ENUM ('ok');\n"
        "CREATE SEQUENCE s;\n"
        "CREATE DOMAIN d AS INT;\n"
    )
    ordered = _ordered("", new)
    assert ordered[:2] == ["ADD_SCHEMA app", "ADD_EXTENSION uuid-ossp"]
    assert ordered[-1] == "ADD_TABLE app.t"


def test_routines_precede_views_and_views_precede_triggers() -> None:
    new = (
        "CREATE TABLE t (a INT);\n"
        "CREATE TRIGGER tr BEFORE UPDATE ON t FOR EACH ROW EXECUTE FUNCTION fn_t();\n"
        "CREATE VIEW v AS SELECT a FROM t;\n"
        "CREATE FUNCTION fn_t() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RETURN NEW; END$$;\n"
        "CREATE POLICY p ON t USING (true);\n"
    )
    kinds = [label.split()[0] for label in _ordered("", new)]
    assert kinds[:3] == ["ADD_TABLE", "ADD_FUNCTION", "ADD_VIEW"]
    assert set(kinds[3:]) == {"ADD_TRIGGER", "ADD_POLICY"}


def test_what_depends_on_a_table_is_dropped_before_it() -> None:
    old = (
        "CREATE TABLE z_parent (id INT PRIMARY KEY);\n"
        "CREATE TABLE a_child (id INT, pid INT REFERENCES z_parent(id));\n"
        "CREATE VIEW v AS SELECT id FROM a_child;\n"
        "CREATE SCHEMA gone;\n"
    )
    assert _ordered(old, "") == [
        "DROP_VIEW v",
        "DROP_TABLE a_child",
        "DROP_TABLE z_parent",
        "DROP_SCHEMA gone",
    ]


def test_a_foreign_key_cycle_is_created_then_closed() -> None:
    """Tables in a cycle are created without the foreign keys that close it, which follow."""
    new = (
        "CREATE TABLE a (id INT PRIMARY KEY, b_id INT"
        ", CONSTRAINT fk_a_b FOREIGN KEY (b_id) REFERENCES b(id));\n"
        "CREATE TABLE b (id INT PRIMARY KEY, a_id INT"
        ", CONSTRAINT fk_b_a FOREIGN KEY (a_id) REFERENCES a(id));\n"
    )
    ordered = apply_order(SchemaDiffer().compare("", new).changes)
    assert [type(c) for c in ordered] == [TableAdded, TableAdded, ForeignKeyAdded, ForeignKeyAdded]
    assert all(not c.table.constraints_of("foreign_key") for c in ordered[:2])
    assert {c.constraint.name for c in ordered[2:]} == {"fk_a_b", "fk_b_a"}


def test_a_table_outside_the_cycle_keeps_its_foreign_key() -> None:
    new = (
        "CREATE TABLE a (id INT PRIMARY KEY, b_id INT REFERENCES b(id));\n"
        "CREATE TABLE b (id INT PRIMARY KEY, a_id INT REFERENCES a(id));\n"
        "CREATE TABLE c (id INT, a_id INT REFERENCES a(id));\n"
    )
    ordered = apply_order(SchemaDiffer().compare("", new).changes)
    (c,) = [x for x in ordered if isinstance(x, TableAdded) and x.table.name == "c"]
    assert len(c.table.constraints_of("foreign_key")) == 1
    assert ordered.index(c) == 2


@pytest.mark.parametrize("old", ["", "CREATE TABLE t (a INT);"])
def test_the_order_of_independent_changes_is_the_differs(old: str) -> None:
    new = "CREATE TABLE t (a INT, b INT, c INT);\nCREATE TABLE u (x INT);\n"
    changes = SchemaDiffer().compare(old, new).changes
    assert apply_order(changes) == changes


def test_a_tview_is_created_after_what_it_reads_and_dropped_before_it() -> None:
    """A pg_tviews TVIEW reads tables, views and routines (#504); its view depends on them."""
    tree = (
        "CREATE TABLE tv_user AS SELECT pk_user, label FROM v_user;\n"
        "CREATE VIEW v_user AS SELECT pk_user, fn_label(name) AS label FROM tb_user;\n"
        "CREATE FUNCTION fn_label(t TEXT) RETURNS TEXT LANGUAGE sql AS $$ SELECT t $$;\n"
        "CREATE TABLE tb_user (pk_user BIGINT PRIMARY KEY, name TEXT);\n"
    )
    assert _ordered("", tree) == [
        "ADD_TABLE tb_user",
        "ADD_FUNCTION fn_label(text)",
        "ADD_VIEW v_user",
        "ADD_TVIEW tv_user",
    ]
    assert _ordered(tree, "")[0] == "DROP_TVIEW tv_user"


def test_a_tables_indexes_are_detached_before_its_columns_change_and_attached_after() -> None:
    """The down undoes the up in reverse, so an index rebuilt on renamed columns must
    be dropped before them and created after them, or the down recreates the old index
    on a column that is not back yet."""
    old = "CREATE TABLE u (full_name TEXT); CREATE INDEX u_i ON u (full_name);"
    new = "CREATE TABLE u (first_name TEXT, last_name TEXT); CREATE INDEX u_i ON u (first_name, last_name);"
    changes = apply_order(SchemaDiffer().compare(old, new).changes)
    assert [c.to_wire().type for c in changes] == [
        "DROP_INDEX",
        "RENAME_COLUMN",
        "ADD_COLUMN",
        "ADD_INDEX",
    ]


def test_a_matview_index_pair_stays_drop_then_add() -> None:
    """Each rebuilt index keeps its drop before its add, whatever relation it is on."""
    base = "CREATE TABLE t (a int, b int);\nCREATE MATERIALIZED VIEW mv AS SELECT a, b FROM t;\n"
    old = base + "CREATE INDEX ix_t ON t (a);\nCREATE INDEX ix_mv ON mv (a);\n"
    new = base + "CREATE INDEX ix_t ON t (b);\nCREATE INDEX ix_mv ON mv (b);\n"
    changes = apply_order(SchemaDiffer().compare(old, new).changes)
    assert [(c.to_wire().type, c.to_wire().table) for c in changes] == [
        ("DROP_INDEX", "t"),
        ("ADD_INDEX", "t"),
        ("DROP_INDEX", "mv"),
        ("ADD_INDEX", "mv"),
    ]


def test_a_tview_index_added_runs_after_its_tview_is_replaced() -> None:
    """A replace may add the column the index names, and pg_tviews refuses a rebuild
    over an invalid index: every drop runs before the replace, every add after it."""
    base = "CREATE TABLE t (a int, b int);\n"
    old = (
        base + "CREATE TABLE tv_a AS SELECT a FROM t;\n"
        "CREATE TABLE tv_b AS SELECT a FROM t;\n"
        "CREATE INDEX ix_tv_a ON tv_a (a);\nCREATE INDEX ix_tv_b ON tv_b (a);\n"
    )
    new = (
        base + "CREATE TABLE tv_a AS SELECT a, b FROM t;\n"
        "CREATE TABLE tv_b AS SELECT a FROM t;\n"
        "CREATE INDEX ix_tv_a ON tv_a (b);\n"
    )
    changes = apply_order(SchemaDiffer().compare(old, new).changes)
    shapes = [
        (type(c).__name__, getattr(c, "relation_kind", c.ref.kind), c.ref.name) for c in changes
    ]
    assert shapes == [
        ("IndexDropped", "tview", "tv_a"),
        ("IndexDropped", "tview", "tv_b"),
        ("ObjectReplaced", "tview", "tv_a"),
        ("IndexAdded", "tview", "tv_a"),
    ]
