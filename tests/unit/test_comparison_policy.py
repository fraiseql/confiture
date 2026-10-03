"""How two schemas are compared follows from who wrote each side.

Two trees are compared as written, renames detected (``AUTHOR``). A tree and a
database are compared through every parity rule PostgreSQL's rewrites call for,
and nothing is renamed by similarity (``CATALOGUED``). Two databases are compared
exactly (``EXACT``). Each rule of ``PARITY_NORMALISATIONS`` is code the
comparison runs, not prose a test fixture reads: dropping any one of them changes
what the normalisation says about a model that exercises it.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from confiture.core.differ import (
    AUTHOR,
    CATALOGUED,
    EXACT,
    SchemaDiffer,
    Side,
    policy_between,
)
from confiture.core.schema_model import (
    ALL_PARITY_RULES,
    PARITY_NORMALISATIONS,
    Constraint,
    Index,
    RelationName,
    SchemaModel,
    Table,
    TView,
    normalise_for_parity,
    tview_ref,
)
from confiture.core.schema_read import read_text

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "every_change"


@pytest.mark.parametrize(
    ("old", "new", "policy"),
    [
        ("author", "author", AUTHOR),
        ("author", "catalog", CATALOGUED),
        ("catalog", "author", CATALOGUED),
        ("catalog", "catalog", EXACT),
    ],
)
def test_the_policy_follows_from_both_sources(old, new, policy) -> None:
    assert policy_between(old, new) == policy


def test_a_tree_is_the_authors_and_the_wire_says_so() -> None:
    model = read_text("CREATE TABLE t (id INT);").model
    assert model.source == "author"
    live = replace(model, source="catalog")
    assert SchemaModel.from_json(live.to_json()).source == "catalog"


def test_a_tree_and_a_database_are_compared_through_every_parity_rule() -> None:
    assert CATALOGUED.rules == frozenset(PARITY_NORMALISATIONS) == ALL_PARITY_RULES
    assert not CATALOGUED.renames
    assert AUTHOR.renames
    assert AUTHOR.rules == EXACT.rules == frozenset()


# A model that exercises every rule: each part is something one rule rewrites.
EXERCISED = """
CREATE TABLE parent (id INT PRIMARY KEY);
CREATE TABLE child (
    id SERIAL,
    pid INT CONSTRAINT child_pid_fkey REFERENCES parent,
    s VARCHAR(5) DEFAULT 'x',
    CONSTRAINT a_check CHECK (id > 0)
);
CREATE INDEX child_s ON child (lower(s));
CREATE SEQUENCE seq MINVALUE 1 MAXVALUE 9223372036854775807;
CREATE FUNCTION f(a int8) RETURNS int4 LANGUAGE sql AS 'select 1';
CREATE VIEW v AS SELECT 1 AS one;
"""


def _exercised() -> SchemaModel:
    model = read_text(EXERCISED).model
    tables = dict(model.tables)
    ref, parent = next((r, t) for r, t in tables.items() if t.name == "parent")
    backing = Index(name="parent_pkey", table=parent.relation, columns=("id",), unique=True)
    tables[ref] = replace(parent, indexes=(replace(backing, backs_constraint=True),))
    tview = TView(name="tv_x", fillfactor=85)
    return replace(model, tables=tables, tviews={tview_ref(tview): tview})


@pytest.mark.parametrize("rule", sorted(PARITY_NORMALISATIONS))
def test_every_parity_rule_rewrites_something(rule: str) -> None:
    model = _exercised()
    without = normalise_for_parity(model, ALL_PARITY_RULES - {rule})
    assert normalise_for_parity(model) != without, f"{rule!r} rewrites nothing"


def test_two_trees_compare_as_they_always_have() -> None:
    old, new = ((FIXTURES / f"{side}.sql").read_text() for side in ("old", "new"))
    by_text = SchemaDiffer().compare(old, new)
    by_sides = SchemaDiffer().compare_sides(
        Side.of(read_text(old)), Side.of(read_text(new)), AUTHOR
    )
    assert [str(c) for c in by_sides.changes] == [str(c) for c in by_text.changes]
    assert by_text.changes


TREE = """
CREATE TABLE parent (id INT PRIMARY KEY);
CREATE TABLE child (
    id SERIAL,
    pid INT REFERENCES parent,
    s TEXT DEFAULT 'x' CHECK (s <> '')
);
"""


def _as_catalogued(model: SchemaModel) -> SchemaModel:
    """*model* the way PostgreSQL's catalog reads the database built from it."""
    tables: dict = {}
    for ref, table in model.tables.items():
        named = tuple(
            replace(c, name=f"{table.name}_{'_'.join(c.columns) or 's'}_{suffix}")
            for c in table.constraints
            for suffix in [{"foreign_key": "fkey", "check": "check", "primary_key": "pkey"}[c.kind]]
        )
        backing = tuple(
            Index(
                name=f"{table.name}_pkey",
                table=RelationName("public", table.name),
                columns=c.columns,
                unique=True,
                backs_constraint=True,
            )
            for c in table.constraints_of("primary_key")
        )
        columns = tuple(
            replace(
                col,
                default=f"{col.default}::text" if col.default else col.default,
                type_text=None,
            )
            for col in table.columns
        )
        tables[ref] = Table(
            name=table.name,
            schema="public",
            columns=columns,
            constraints=named,
            indexes=backing,
        )
    return replace(model, tables=tables, source="catalog")


def test_a_database_built_from_a_tree_is_no_change_from_it() -> None:
    tree = read_text(TREE)
    live = Side(model=_as_catalogued(tree.model))
    assert SchemaDiffer().compare_sides(Side.of(tree), live).changes == []
    assert SchemaDiffer().compare_sides(live, Side.of(tree)).changes == []


def test_the_same_pair_read_as_two_trees_is_full_of_changes() -> None:
    tree = read_text(TREE)
    live = Side(model=_as_catalogued(tree.model))
    kinds = {
        type(c).__name__ for c in SchemaDiffer().compare_sides(Side.of(tree), live, AUTHOR).changes
    }
    assert {"ForeignKeyAdded", "ForeignKeyDropped", "IndexAdded", "ColumnDefaultChanged"} <= kinds


def test_a_database_renames_nothing_by_similarity() -> None:
    old = Side.of(read_text("CREATE TABLE orders (id INT);"))
    new = Side(
        model=replace(read_text("CREATE TABLE orders_archive (id INT);").model, source="catalog")
    )
    kinds = [type(c).__name__ for c in SchemaDiffer().compare_sides(old, new).changes]
    assert kinds == ["TableDropped", "TableAdded"]
    assert [
        type(c).__name__
        for c in SchemaDiffer()
        .compare_sides(old, replace(new, model=replace(new.model, source="author")))
        .changes
    ] == ["TableRenamed"]


def test_a_named_constraint_is_still_its_name() -> None:
    tree = read_text(
        "CREATE TABLE p (id INT PRIMARY KEY);"
        "CREATE TABLE c (pid INT CONSTRAINT fk_parent REFERENCES p);"
    )
    model = tree.model
    ref, child = next((r, t) for r, t in model.tables.items() if t.name == "c")
    (fk,) = child.constraints
    renamed = replace(child, constraints=(replace(fk, name="fk_other"),))
    live = Side(model=replace(model, tables={**model.tables, ref: renamed}, source="catalog"))
    kinds = sorted(
        type(c).__name__ for c in SchemaDiffer().compare_sides(Side.of(tree), live).changes
    )
    assert kinds == ["ForeignKeyAdded", "ForeignKeyDropped"]


def test_constraint_kind_is_kept_by_the_rules() -> None:
    # The rules decide identity and change; the change carries what each side wrote.
    tree = read_text(TREE)
    live = _as_catalogued(tree.model)
    child = next(t for t in live.tables.values() if t.name == "child")
    extra = Constraint(kind="unique", name="child_s_key", columns=("s",))
    live = replace(
        live,
        tables={
            **live.tables,
            **{
                r: replace(child, constraints=(*child.constraints, extra))
                for r, t in live.tables.items()
                if t.name == "child"
            },
        },
    )
    (change,) = SchemaDiffer().compare_sides(Side.of(tree), Side(model=live)).changes
    assert type(change).__name__ == "UniqueConstraintAdded"
    assert change.constraint.name == "child_s_key"
