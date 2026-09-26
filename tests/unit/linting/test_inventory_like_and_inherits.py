"""The columns a table gets through ``LIKE``, ``INHERITS`` and ``PARTITION OF`` (#467).

``LIKE`` copies the source's columns into the new table once, when it is created:
they are the new table's own from then on, so the reader writes them into it, at
the clause's position, as the source stands at that statement. Every column keeps
its ``NOT NULL``; a default, an identity and a generation expression are copied
only when the clause says ``INCLUDING`` them; no constraint is (a foreign key
never, in PostgreSQL). ``INHERITS`` and ``PARTITION OF`` do not copy: the child
holds its parent's columns for as long as it is one, so
:func:`~confiture.core.linting.inventory.inherit_columns` answers them from the
tree's final state, for the readers that compare against PostgreSQL.
"""

from __future__ import annotations

from confiture.core.drift import parse_expected_schema
from confiture.core.linting.inventory import (
    SchemaObject,
    build_inventory,
    build_model,
    inherit_columns,
)

_SOURCE = (
    "CREATE TABLE app.src (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,\n"
    "  code text NOT NULL DEFAULT 'x', fk bigint REFERENCES app.other (id),\n"
    "  total int GENERATED ALWAYS AS (1) STORED);\n"
)


def _table(sql: str, name: str) -> SchemaObject:
    found = build_inventory(sql).find("app", name)
    assert found is not None
    return found


def _facts(table: SchemaObject) -> list[tuple[str, bool, str | None, str | None, str | None]]:
    return [
        (c.folded, c.not_null, c.default, c.identity, c.generated and "generated")
        for c in table.columns
    ]


# -- LIKE ------------------------------------------------------------------------


def test_like_copies_the_columns_at_the_clauses_position() -> None:
    table = _table(_SOURCE + "CREATE TABLE app.cp (a int, LIKE app.src, b int);\n", "cp")

    assert [c.folded for c in table.columns] == ["a", "id", "code", "fk", "total", "b"]


def test_like_copies_not_null_and_nothing_else_by_default() -> None:
    table = _table(_SOURCE + "CREATE TABLE app.cp (LIKE app.src);\n", "cp")

    assert _facts(table) == [
        ("id", True, None, None, None),
        ("code", True, None, None, None),
        ("fk", False, None, None, None),
        ("total", False, None, None, None),
    ]
    assert table.constraints == []
    assert not any(c.primary_key for c in table.columns)


def test_like_including_all_copies_defaults_identity_and_generation() -> None:
    table = _table(_SOURCE + "CREATE TABLE app.cp (LIKE app.src INCLUDING ALL);\n", "cp")

    assert _facts(table) == [
        ("id", True, None, "always", None),
        ("code", True, "'x'", None, None),
        ("fk", False, None, None, None),
        ("total", False, None, None, "generated"),
    ]
    assert not [c for c in table.constraints if c.kind == "foreign_key"]


def test_like_excluding_what_all_includes_leaves_it_out() -> None:
    table = _table(
        _SOURCE + "CREATE TABLE app.cp (LIKE app.src INCLUDING ALL EXCLUDING DEFAULTS);\n", "cp"
    )

    assert [c.default for c in table.columns] == [None, None, None, None]


def test_like_reads_the_source_as_it_stands_at_the_statement() -> None:
    sql = (
        "CREATE TABLE app.src (a int);\n"
        "ALTER TABLE app.src ADD COLUMN b int;\n"
        "CREATE TABLE app.cp (LIKE app.src);\n"
        "ALTER TABLE app.src ADD COLUMN c int;\n"
    )

    assert [c.folded for c in _table(sql, "cp").columns] == ["a", "b"]


def test_like_of_a_table_the_tree_does_not_declare_copies_nothing() -> None:
    assert [
        c.folded for c in _table("CREATE TABLE app.cp (a int, LIKE ext.t);\n", "cp").columns
    ] == ["a"]


def test_the_model_carries_the_copied_columns() -> None:
    model = build_model(_SOURCE + "CREATE TABLE app.cp (LIKE app.src);\n")

    (copy,) = [t for t in model.tables.values() if t.name == "cp"]
    assert [c.folded for c in copy.columns] == ["id", "code", "fk", "total"]


# -- INHERITS and PARTITION OF ------------------------------------------------------


def _inherited(sql: str, name: str) -> SchemaObject:
    found = inherit_columns(build_inventory(sql)).find("app", name)
    assert found is not None
    return found


def test_inherits_puts_the_parents_columns_first() -> None:
    table = _inherited(
        "CREATE TABLE app.p (id int NOT NULL DEFAULT 1, name text);\n"
        "CREATE TABLE app.c (extra int) INHERITS (app.p);\n",
        "c",
    )

    assert [(c.folded, c.not_null, c.default) for c in table.columns] == [
        ("id", True, "1"),
        ("name", False, None),
        ("extra", False, None),
    ]


def test_a_column_the_child_redeclares_merges_into_the_inherited_one() -> None:
    table = _inherited(
        "CREATE TABLE app.p (id int, name text);\n"
        "CREATE TABLE app.c (name text NOT NULL, extra int) INHERITS (app.p);\n",
        "c",
    )

    assert [(c.folded, c.not_null) for c in table.columns] == [
        ("id", False),
        ("name", True),
        ("extra", False),
    ]


def test_inherits_reads_every_parent_and_their_parents() -> None:
    table = _inherited(
        "CREATE TABLE app.g (a int);\n"
        "CREATE TABLE app.p (b int) INHERITS (app.g);\n"
        "CREATE TABLE app.q (c int, a int);\n"
        "CREATE TABLE app.c (d int) INHERITS (app.p, app.q);\n",
        "c",
    )

    assert [c.folded for c in table.columns] == ["a", "b", "c", "d"]


def test_inherits_takes_no_primary_key_and_no_foreign_key() -> None:
    table = _inherited(
        "CREATE TABLE app.p (id int PRIMARY KEY, fk int REFERENCES app.o (id));\n"
        "CREATE TABLE app.c () INHERITS (app.p);\n",
        "c",
    )

    assert [(c.folded, c.not_null, c.primary_key) for c in table.columns] == [
        ("id", True, False),
        ("fk", False, False),
    ]
    assert table.constraints == []


def test_inheritance_is_read_from_the_trees_final_state() -> None:
    table = _inherited(
        "CREATE TABLE app.p (a int);\n"
        "CREATE TABLE app.c () INHERITS (app.p);\n"
        "ALTER TABLE app.p ADD COLUMN b int;\n",
        "c",
    )

    assert [c.folded for c in table.columns] == ["a", "b"]


def test_a_partition_has_its_parents_columns_with_its_own_options() -> None:
    table = _inherited(
        "CREATE TABLE app.p (id int NOT NULL, at date, note text) PARTITION BY RANGE (at);\n"
        "CREATE TABLE app.p1 PARTITION OF app.p (note DEFAULT 'n')\n"
        "  FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');\n",
        "p1",
    )

    assert [(c.folded, c.type_key is not None, c.default) for c in table.columns] == [
        ("id", True, None),
        ("at", True, None),
        ("note", True, "'n'"),
    ]


def test_an_inheritance_cycle_ends() -> None:
    table = _inherited(
        "CREATE TABLE app.a (x int) INHERITS (app.b);\nCREATE TABLE app.b (y int) INHERITS (app.a);\n",
        "a",
    )

    assert {c.folded for c in table.columns} == {"x", "y"}


def test_the_inventory_it_was_given_is_left_as_it_was() -> None:
    inventory = build_inventory(
        "CREATE TABLE app.p (a int);\nCREATE TABLE app.c (b int) INHERITS (app.p);\n"
    )
    inherit_columns(inventory)

    child = inventory.find("app", "c")
    assert child is not None
    assert [c.folded for c in child.columns] == ["b"]


def test_drift_expects_an_inheriting_tables_columns() -> None:
    model = parse_expected_schema(
        "CREATE TABLE app.p (a int);\nCREATE TABLE app.c (b int) INHERITS (app.p);\n"
    ).model

    (child,) = [t for t in model.tables.values() if t.name == "c"]
    assert [c.folded for c in child.columns] == ["a", "b"]
