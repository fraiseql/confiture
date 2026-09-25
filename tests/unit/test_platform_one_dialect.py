"""The seam spells each concept one way (#374).

``database`` is what a call runs on, a URL or a connection, wherever a call runs
on one; ``seeds`` is the seed files, a directory or a list, wherever a call reads
them; an error is named ``…Error``. And every change names its object the way the
model keys it, whatever its other fields are called: ``change.ref``.
"""

from __future__ import annotations

import typing
from collections.abc import Callable
from pathlib import Path

import pytest

from confiture import platform
from confiture.core.schema_model import ref_for

TABLE = platform.Table(name="item", schema="app")
COLUMN = platform.Column(name="label", folded="label", line=1)
INDEX = platform.Index(name="ix", table="app.item", columns=("label",))
FK = platform.Constraint(kind="foreign_key", name="fk", columns=("x",), ref_table="app.other")
ENUM = platform.EnumType(name="mood", schema="app", values=("ok",))
SEQUENCE = platform.Sequence(name="counter", schema="app")
VIEW_REF = ref_for("view", "app", "v")

ITEM = ref_for("table", "app", "item")
MOOD = ref_for("type", "app", "mood")
COUNTER = ref_for("sequence", "app", "counter")


def _object() -> platform.DDLObject:
    return platform.DDLObject(
        ref=VIEW_REF, definition="v", create_sql="CREATE VIEW app.v AS SELECT 1"
    )


#: One instance of every variant, and the reference it must name: the key the
#: model holds the changed object under — the table for anything on a table.
EXAMPLES: dict[type, tuple[Callable[[], object], platform.ObjectRef]] = {
    platform.TableAdded: (lambda: platform.TableAdded(TABLE), ITEM),
    platform.TableDropped: (lambda: platform.TableDropped(TABLE), ITEM),
    platform.TableRenamed: (
        lambda: platform.TableRenamed(TABLE, platform.Table(name="items", schema="app")),
        ITEM,
    ),
    platform.ColumnAdded: (lambda: platform.ColumnAdded("app.item", COLUMN), ITEM),
    platform.ColumnDropped: (lambda: platform.ColumnDropped("app.item", COLUMN), ITEM),
    platform.ColumnRenamed: (lambda: platform.ColumnRenamed("app.item", "a", "b"), ITEM),
    platform.ColumnTypeChanged: (
        lambda: platform.ColumnTypeChanged("app.item", COLUMN, COLUMN),
        ITEM,
    ),
    platform.ColumnNullabilityChanged: (
        lambda: platform.ColumnNullabilityChanged("app.item", "label", nullable=True),
        ITEM,
    ),
    platform.ColumnDefaultChanged: (
        lambda: platform.ColumnDefaultChanged("app.item", "label", None, "'x'"),
        ITEM,
    ),
    platform.IndexAdded: (lambda: platform.IndexAdded("app.item", INDEX), ITEM),
    platform.IndexDropped: (lambda: platform.IndexDropped("app.item", INDEX), ITEM),
    platform.ForeignKeyAdded: (lambda: platform.ForeignKeyAdded("app.item", FK), ITEM),
    platform.ForeignKeyDropped: (lambda: platform.ForeignKeyDropped("app.item", FK), ITEM),
    platform.CheckConstraintAdded: (lambda: platform.CheckConstraintAdded("app.item", FK), ITEM),
    platform.CheckConstraintDropped: (
        lambda: platform.CheckConstraintDropped("app.item", FK),
        ITEM,
    ),
    platform.UniqueConstraintAdded: (
        lambda: platform.UniqueConstraintAdded("app.item", FK),
        ITEM,
    ),
    platform.UniqueConstraintDropped: (
        lambda: platform.UniqueConstraintDropped("app.item", FK),
        ITEM,
    ),
    platform.ExclusionConstraintAdded: (
        lambda: platform.ExclusionConstraintAdded("app.item", FK),
        ITEM,
    ),
    platform.ExclusionConstraintDropped: (
        lambda: platform.ExclusionConstraintDropped("app.item", FK),
        ITEM,
    ),
    platform.EnumTypeAdded: (lambda: platform.EnumTypeAdded(ENUM), MOOD),
    platform.EnumTypeDropped: (lambda: platform.EnumTypeDropped(ENUM), MOOD),
    platform.EnumValuesChanged: (
        lambda: platform.EnumValuesChanged("app.mood", added=("meh",), removed=()),
        MOOD,
    ),
    platform.SequenceAdded: (lambda: platform.SequenceAdded(SEQUENCE), COUNTER),
    platform.SequenceDropped: (lambda: platform.SequenceDropped(SEQUENCE), COUNTER),
    platform.ObjectAdded: (lambda: platform.ObjectAdded(VIEW_REF, _object()), VIEW_REF),
    platform.ObjectDropped: (lambda: platform.ObjectDropped(VIEW_REF, _object()), VIEW_REF),
    platform.ObjectReplaced: (
        lambda: platform.ObjectReplaced(VIEW_REF, _object(), _object()),
        VIEW_REF,
    ),
}


@pytest.mark.parametrize(
    "variant", typing.get_args(platform.SchemaChange), ids=lambda v: v.__name__
)
def test_every_change_names_its_object(variant: type) -> None:
    """Parametrised over the union, so a variant added without a ``ref`` fails here."""
    build, expected = EXAMPLES[variant]
    ref = build().ref  # type: ignore[attr-defined]
    assert ref == expected
    assert ref.display == expected.display


def test_an_unqualified_change_names_the_default_schemas_object() -> None:
    change = platform.ColumnAdded("item", COLUMN)
    assert change.ref == ref_for("table", None, "item")
    assert change.ref.display == "item"


def test_a_diffs_references_are_the_models_keys() -> None:
    """What a consumer does with ``ref``: look the object up in the model it came from."""
    old = (
        "CREATE SCHEMA app;\nCREATE TYPE app.mood AS ENUM ('ok');\n"
        "CREATE TABLE app.item (id INT PRIMARY KEY, label TEXT);\n"
        "CREATE SEQUENCE app.gone;\n"
    )
    new = (
        "CREATE SCHEMA app;\nCREATE TYPE app.mood AS ENUM ('ok', 'meh');\n"
        "CREATE TABLE app.item (id INT PRIMARY KEY, label TEXT NOT NULL, note TEXT);\n"
        "CREATE INDEX ix_label ON app.item (label);\nCREATE TABLE app.extra (id INT);\n"
    )
    before, after = platform.parse_schema(old), platform.parse_schema(new)
    keys = {
        *before.tables,
        *after.tables,
        *before.enum_types,
        *after.enum_types,
        *before.sequences,
        *after.sequences,
    }
    changes = [
        c for c in platform.diff(old, new).changes if not isinstance(c, platform.ObjectAdded)
    ]
    assert {type(c).__name__ for c in changes} >= {
        "ColumnAdded",
        "ColumnNullabilityChanged",
        "IndexAdded",
        "TableAdded",
        "EnumValuesChanged",
        "SequenceDropped",
    }
    assert [c for c in changes if c.ref not in keys] == []


def test_validate_seeds_takes_seeds_and_database(tmp_path: Path) -> None:
    seeds, schema = tmp_path / "seeds", tmp_path / "schema"
    seeds.mkdir()
    schema.mkdir()
    report = platform.validate_seeds(seeds=seeds, schema_dir=schema, max_level=1, database=None)
    assert report.violations == []


@pytest.mark.parametrize(
    "keyword", [{"seeds_dir": "x"}, {"database_url": "postgresql://"}], ids=lambda k: next(iter(k))
)
def test_validate_seeds_has_no_second_spelling(keyword: dict[str, str], tmp_path: Path) -> None:
    arguments: dict[str, object] = {"seeds": tmp_path, "schema_dir": tmp_path, **keyword}
    if "seeds_dir" in keyword:
        del arguments["seeds"]
    with pytest.raises(TypeError, match=next(iter(keyword))):
        platform.validate_seeds(**arguments)  # type: ignore[arg-type]


def test_validate_seeds_levels_four_and_five_need_a_database(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="database"):
        platform.validate_seeds(tmp_path, schema_dir=tmp_path, max_level=4)


def test_validate_seeds_refuses_a_database_that_is_neither_a_url_nor_a_connection(
    tmp_path: Path,
) -> None:
    with pytest.raises(TypeError, match="database"):
        platform.validate_seeds(tmp_path, schema_dir=tmp_path, max_level=4, database=42)  # type: ignore[arg-type]


def test_a_cycle_is_a_dependency_cycle_error() -> None:
    model = platform.parse_schema(
        "CREATE TABLE a (id INT PRIMARY KEY, b_id INT);\n"
        "CREATE TABLE b (id INT PRIMARY KEY, a_id INT REFERENCES a);\n"
        "ALTER TABLE a ADD FOREIGN KEY (b_id) REFERENCES b;\n"
    )
    with pytest.raises(platform.DependencyCycleError) as caught:
        platform.dependency_order(model)
    assert isinstance(caught.value, platform.SchemaError)
    assert not hasattr(platform, "DependencyCycle")


def test_validate_seeds_says_what_it_validates() -> None:
    first_line = (platform.validate_seeds.__doc__ or "").strip().splitlines()[0]
    assert "prep-seed pattern" in first_line
