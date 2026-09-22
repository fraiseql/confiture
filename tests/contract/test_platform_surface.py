"""The contract of ``confiture.platform``: the seam a tool builds on.

A seed generator, a parity fixture, the 2027 crate — each reads a schema into the
one model, orders its tables, asks what a writer may supply and writes seeds the
applier and the validator accept. This file is what they may rely on. Every name
is listed, every signature is pinned by **equality** and every dataclass's fields
with it: widening the seam is an edit here as much as narrowing it, because a
consumer written against this surface reads it by name.

The model's wire is pinned the same way: ``SchemaModel.to_json()`` validates
against the published ``schema-model.schema.json``, and ``from_json`` gives back
the model it was written from, for every tree the model goldens record.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from confiture import platform
from confiture.core.schema_exporter import load_schema

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_GOLDENS = REPO_ROOT / "tests" / "fixtures" / "model_goldens" / "model"

#: The model and the change union.
MODEL = (
    "SchemaModel",
    "ObjectRef",
    "Table",
    "Column",
    "Constraint",
    "Index",
    "EnumType",
    "Sequence",
    "Routine",
    "View",
    "Trigger",
)
CHANGES = (
    "SchemaChange",
    "SchemaDiff",
    "TableAdded",
    "TableDropped",
    "TableRenamed",
    "ColumnAdded",
    "ColumnDropped",
    "ColumnRenamed",
    "ColumnTypeChanged",
    "ColumnNullabilityChanged",
    "ColumnDefaultChanged",
    "IndexAdded",
    "IndexDropped",
    "ForeignKeyAdded",
    "ForeignKeyDropped",
    "CheckConstraintAdded",
    "CheckConstraintDropped",
    "UniqueConstraintAdded",
    "UniqueConstraintDropped",
    "EnumTypeAdded",
    "EnumTypeDropped",
    "EnumValuesChanged",
    "SequenceAdded",
    "SequenceDropped",
    "ObjectAdded",
    "ObjectDropped",
    "ObjectReplaced",
    "RiskTier",
    "tier_of",
)
#: Reading a schema, from DDL or from a database.
READING = ("SchemaSource", "Connection", "parse_schema", "introspect", "diff", "SchemaError")

#: Ordering tables by their foreign keys.
ORDERING = ("dependency_order", "DependencyCycle")

EXPORTS = frozenset(MODEL + CHANGES + READING + ORDERING)

#: ``str(inspect.signature(...))`` of every callable the seam defines. Under
#: ``from __future__ import annotations`` an annotation is its source text.
SIGNATURES: dict[str, str] = {
    "parse_schema": (
        "(source: 'SchemaSource | None' = None, *, env: 'str | None' = None, "
        "project_dir: 'Path | None' = None) -> 'SchemaModel'"
    ),
    "introspect": (
        "(database: 'str | Connection', *, schemas: 'Sequence[str] | None' = None) -> 'SchemaModel'"
    ),
    "diff": "(old: 'SchemaSource', new: 'SchemaSource') -> 'SchemaDiff'",
    "dependency_order": (
        "(model: 'SchemaModel', *, tables: 'Iterable[ObjectRef | str] | None' = None) "
        "-> 'list[ObjectRef]'"
    ),
    "tier_of": "(change: 'SchemaChange') -> 'RiskTier | None'",
    "SchemaModel.to_json": "(self) -> 'str'",
    "SchemaModel.from_json": "(text: 'str') -> 'SchemaModel'",
}


def _fields(cls: type) -> tuple[tuple[str, str], ...]:
    return tuple((f.name, str(f.type)) for f in dataclasses.fields(cls))


#: The fields of every dataclass the seam hands out, name and annotation.
FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "ObjectRef": (
        ("kind", "str"),
        ("schema", "str"),
        ("name", "str"),
        ("signature", "tuple[str, ...] | None"),
        ("display", "str"),
    ),
    "Column": (
        ("name", "str"),
        ("folded", "str"),
        ("line", "int"),
        ("type_text", "str | None"),
        ("type_key", "str | None"),
        ("raw_sql_type", "str | None"),
        ("not_null", "bool"),
        ("default", "str | None"),
        ("identity", "IdentityKind | None"),
        ("generated", "str | None"),
        ("generated_kind", "GeneratedKind | None"),
        ("primary_key", "bool"),
    ),
    "Constraint": (
        ("kind", "ConstraintKind"),
        ("name", "str"),
        ("columns", "tuple[str, ...]"),
        ("ref_table", "str | None"),
        ("ref_columns", "tuple[str, ...]"),
        ("on_delete", "str | None"),
        ("on_update", "str | None"),
        ("expression", "str | None"),
        ("deferrable", "Deferral | None"),
    ),
    "Index": (
        ("name", "str | None"),
        ("table", "str"),
        ("columns", "tuple[str, ...]"),
        ("unique", "bool"),
        ("where", "str | None"),
        ("method", "str | None"),
        ("backs_constraint", "bool"),
    ),
    "Table": (
        ("name", "str"),
        ("schema", "str | None"),
        ("columns", "tuple[Column, ...]"),
        ("constraints", "tuple[Constraint, ...]"),
        ("indexes", "tuple[Index, ...]"),
    ),
    "EnumType": (("name", "str"), ("schema", "str | None"), ("values", "tuple[str, ...]")),
    "Sequence": (
        ("name", "str"),
        ("schema", "str | None"),
        ("start", "int | None"),
        ("increment", "int | None"),
        ("min_value", "int | None"),
        ("max_value", "int | None"),
    ),
    "Routine": (
        ("name", "str"),
        ("schema", "str | None"),
        ("kind", "RoutineKind"),
        ("signature", "str"),
        ("signature_key", "Signature"),
        ("returns", "str | None"),
        ("language", "str | None"),
        ("body", "str | None"),
        ("security_definer", "bool"),
        ("search_path_pinned", "bool"),
        ("volatility", "Volatility"),
    ),
    "View": (
        ("name", "str"),
        ("schema", "str | None"),
        ("materialized", "bool"),
        ("definition", "str | None"),
        ("indexes", "tuple[Index, ...]"),
    ),
    "Trigger": (("name", "str"), ("table", "str"), ("schema", "str | None")),
    "SchemaModel": (
        ("tables", "Mapping[ObjectRef, Table]"),
        ("enum_types", "Mapping[ObjectRef, EnumType]"),
        ("sequences", "Mapping[ObjectRef, Sequence]"),
        ("routines", "Mapping[ObjectRef, tuple[Routine, ...]]"),
        ("views", "Mapping[ObjectRef, View]"),
        ("triggers", "Mapping[ObjectRef, Trigger]"),
    ),
    "SchemaDiff": (("changes", "list[SchemaChange]"), ("warnings", "list[BuildWarning]")),
}


def _resolve(dotted: str) -> object:
    target: object = platform
    for part in dotted.split("."):
        target = getattr(target, part)
    return target


def test_the_seam_exports_exactly_its_names() -> None:
    assert set(platform.__all__) == EXPORTS


@pytest.mark.parametrize("name", sorted(EXPORTS))
def test_every_name_is_importable(name: str) -> None:
    assert getattr(platform, name, None) is not None, name


@pytest.mark.parametrize("dotted", sorted(SIGNATURES))
def test_every_signature_is_pinned(dotted: str) -> None:
    assert str(inspect.signature(_resolve(dotted))) == SIGNATURES[dotted]


@pytest.mark.parametrize("name", sorted(FIELDS))
def test_every_dataclass_is_pinned(name: str) -> None:
    assert _fields(getattr(platform, name)) == FIELDS[name]


def test_every_callable_is_pinned() -> None:
    callables = {name for name in EXPORTS if inspect.isfunction(getattr(platform, name, None))}
    assert callables <= set(SIGNATURES), sorted(callables - set(SIGNATURES))


def _goldens() -> list[Path]:
    return sorted(MODEL_GOLDENS.glob("*.json"))


def test_the_goldens_were_found() -> None:
    assert len(_goldens()) >= 10


@pytest.mark.parametrize("golden", _goldens(), ids=lambda p: p.stem)
def test_the_published_schema_validates_the_model_wire(golden: Path) -> None:
    model = platform.SchemaModel.from_json(golden.read_text())
    validator = Draft202012Validator(load_schema("schema-model.schema.json"))
    errors = sorted(validator.iter_errors(json.loads(model.to_json())), key=str)
    assert errors == [], errors[0].message if errors else ""


@pytest.mark.parametrize("golden", _goldens(), ids=lambda p: p.stem)
def test_the_wire_round_trips(golden: Path) -> None:
    model = platform.SchemaModel.from_json(golden.read_text())
    assert json.loads(model.to_json()) == json.loads(golden.read_text())
    assert platform.SchemaModel.from_json(model.to_json()) == model


def test_the_wire_is_canonical() -> None:
    """Sorted keys, so two writers of one model write one text."""
    model = platform.parse_schema(env="local", project_dir=REPO_ROOT)
    text = model.to_json()
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True)


#: The trees the model goldens record from a project's own ``build --env``.
ENV_TREES = {
    "db-schema": (".", "local"),
    "01-basic-migration": ("examples/01-basic-migration", "local"),
    "02-fraiseql-integration": ("examples/02-fraiseql-integration", "local"),
    "04-production-sync-anonymization": ("examples/04-production-sync-anonymization", "production"),
    "05-multi-environment-workflow": ("examples/05-multi-environment-workflow", "ci"),
    "07-comment-validation": ("examples/07-comment-validation", "local"),
    "basic": ("examples/basic", "local"),
}


@pytest.mark.parametrize("tree", sorted(ENV_TREES))
def test_parse_schema_reads_what_the_build_reads(tree: str) -> None:
    """``parse_schema(env=…)`` is the model the goldens recorded from ``build --env``."""
    project, env = ENV_TREES[tree]
    recorded = platform.SchemaModel.from_json((MODEL_GOLDENS / f"{tree}.json").read_text())
    assert platform.parse_schema(env=env, project_dir=REPO_ROOT / project) == recorded


def test_parse_schema_reads_a_directory_and_text_alike(tmp_path: Path) -> None:
    (tmp_path / "10_tables").mkdir()
    (tmp_path / "10_tables" / "b.sql").write_text("ALTER TABLE a ADD COLUMN y INT;\n")
    (tmp_path / "00_a.sql").write_text("CREATE TABLE a (x INT);\n")
    from_dir = platform.parse_schema(tmp_path)
    from_text = platform.parse_schema("CREATE TABLE a (x INT);\nALTER TABLE a ADD COLUMN y INT;\n")
    assert [c.name for t in from_dir.tables.values() for c in t.columns] == ["x", "y"]
    assert from_dir.tables.keys() == from_text.tables.keys()


def test_parse_schema_takes_one_source() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        platform.parse_schema("CREATE TABLE a (x INT);", env="local")
    with pytest.raises(ValueError, match="exactly one"):
        platform.parse_schema()


def test_a_schema_postgresql_rejects_is_a_schema_error() -> None:
    with pytest.raises(platform.SchemaError) as caught:
        platform.parse_schema("CREATE TABLE (;")
    assert caught.value.error_code == "DIFFER_400"


def test_parse_schema_reads_past_a_copy_block() -> None:
    model = platform.parse_schema(
        "CREATE TABLE a (x TEXT);\nCOPY a (x) FROM stdin;\nnot; sql\n\\.\nCREATE TABLE b (y INT);\n"
    )
    assert sorted(ref.name for ref in model.tables) == ["a", "b"]


def test_diff_compares_two_sources_whole() -> None:
    """Views and routines included: they are what a model-to-model diff would lose."""
    result = platform.diff(
        "CREATE TABLE a (x INT);",
        "CREATE TABLE a (x INT, y TEXT);\nCREATE VIEW v AS SELECT x FROM a;",
    )
    assert isinstance(result, platform.SchemaDiff)
    assert {type(change).__name__ for change in result.changes} == {"ColumnAdded", "ObjectAdded"}
    added = next(c for c in result.changes if isinstance(c, platform.ColumnAdded))
    assert isinstance(platform.tier_of(added), platform.RiskTier)


@pytest.mark.parametrize(
    "name",
    [
        "Column",
        "Constraint",
        "Index",
        "Table",
        "EnumType",
        "Sequence",
        "Routine",
        "View",
        "Trigger",
    ],
)
def test_the_published_schema_declares_every_field(name: str) -> None:
    """A field the model gains and the schema does not declare is a wire the schema rejects."""
    declared = load_schema("schema-model.schema.json")["$defs"][name]
    fields = [f.name for f in dataclasses.fields(getattr(platform, name))]
    assert list(declared["properties"]) == fields
    assert declared["required"] == fields
