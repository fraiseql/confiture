"""One schema model: a table, a column, a constraint or an index is defined once.

``core/schema_model.py`` holds the model every reader of a schema answers in.
Before it there were six models of a table in this package, and a column's
nullability was derived six ways from four sources; a fact one model carried and
another did not reached an artefact every time — a primary key declared at table
level read as a nullable column, a generated ``CREATE TABLE`` that lost a column's
identity.

This fails on a class outside that module which is *named* like one of the model's
types, or which *carries the fields* of one — the second shape is how the other
five models were born, since none of them was called ``Table``. The classes that
already exist are listed with the question each answers instead, the way the
one-lexer and one-canonicaliser guards list theirs; an entry that matches nothing
fails, so the list shrinks as models retire.
"""

from __future__ import annotations

import ast
from pathlib import Path

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent
MODEL_MODULE = PACKAGE / "core" / "schema_model.py"

#: The model's types. A class of one of these names outside the model module is
#: a second model of that thing.
MODEL_NAMES = frozenset(
    {"Table", "Column", "Constraint", "Index", "EnumType", "Sequence", "Routine", "View", "Trigger"}
)

#: What each model's fields look like: a class whose annotated fields include
#: any one of these sets is modelling that thing, whatever it is called.
FIELD_SIGNATURES: dict[str, tuple[frozenset[str], ...]] = {
    "Table": (frozenset({"name", "columns"}), frozenset({"table_name", "columns"})),
    "Column": (
        frozenset({"name", "nullable"}),
        frozenset({"name", "not_null"}),
        frozenset({"name", "data_type"}),
        frozenset({"column_name", "data_type"}),
    ),
    "Constraint": (
        frozenset({"columns", "ref_table"}),
        frozenset({"constraint_type", "columns"}),
        frozenset({"name", "table", "expression"}),
    ),
    "Index": (frozenset({"columns", "unique"}), frozenset({"columns", "is_unique"})),
    "EnumType": (frozenset({"name", "schema", "values"}),),
    "Sequence": (frozenset({"start", "increment"}),),
    "Routine": (
        frozenset({"param_types"}),
        frozenset({"arg_types", "input_types"}),
        frozenset({"params", "return_type"}),
        frozenset({"name", "signature"}),
        frozenset({"name", "is_security_definer"}),
    ),
    "View": (frozenset({"relkind", "definition"}), frozenset({"name", "definition", "indexes"})),
}

_SNAPSHOT = (
    "the pytest plugin's own snapshot of a live database, part of the `pytest11` "
    "entry point's surface and shaped for its users' assertions"
)

_RETIRING = (
    "a routine or view as a reader held it before the model had routines and views; "
    "it retires as its readers move onto the model"
)

#: ``module:Class`` -> the different question that class answers.
ALLOWED: dict[str, str] = {
    "core/live_objects.py:LiveObject": _RETIRING,
    "core/live_catalog.py:RoutineRow": (
        "a pg_proc row with what the introspector's FunctionInfo needs and the model "
        "does not hold — every argument's name and mode, the cost, the comment, the oid"
    ),
    "models/function_info.py:FunctionInfo": (
        "the input shape of stub_generator, pgtap_generator and the MCP server, a public "
        "surface whose shape the platform seam decides; built from a RoutineRow"
    ),
    "core/linting/libraries/functions.py:_CallableDefinition": (
        "one CREATE FUNCTION as func_001 reports it, with the file and line a finding needs"
    ),
    "core/linting/libraries/security_definer.py:_FunctionDefRecord": (
        "one CREATE FUNCTION as sec_001 reports it, with the file and line a finding needs"
    ),
    "core/view_manager.py:SavedView": (
        "a dependent view ViewManager drops and re-creates around an ALTER COLUMN TYPE: "
        "its dependency depth, oid, comment and index DDL — fraisier imports ViewManager"
    ),
    "core/linting/inventory.py:SchemaObject": (
        "one CREATE statement as the lint rules read it — any kind, with the file, "
        "line, offset and existence clauses a finding needs; `schema_model()` turns "
        "the inventory into the model"
    ),
    "core/linting/tenant/function_parser.py:InsertStatement": (
        "a parsed INSERT inside a function body: the columns it writes, not a table"
    ),
    "core/seed/validation/prep_seed/level_2_schema.py:TableDefinition": (
        "configuration a prep-seed check is told, not a parse of DDL"
    ),
    "models/introspection.py:IntrospectedColumn": (
        "the `introspect` wire shape, pinned by introspect.schema.json"
    ),
    "models/introspection.py:IntrospectedTable": (
        "the `introspect` wire shape, pinned by introspect.schema.json"
    ),
    "testing/fixtures/schema_snapshotter.py:ColumnInfo": _SNAPSHOT,
    "testing/fixtures/schema_snapshotter.py:ConstraintInfo": _SNAPSHOT,
    "testing/fixtures/schema_snapshotter.py:IndexInfo": _SNAPSHOT,
    "testing/fixtures/schema_snapshotter.py:TableSchema": _SNAPSHOT,
}


def _fields(node: ast.ClassDef) -> set[str]:
    return {
        stmt.target.id
        for stmt in node.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    }


def second_models(source: str) -> list[tuple[str, str]]:
    """``(class name, the model it restates)`` for every such class in *source*."""
    found: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name in MODEL_NAMES:
            found.append((node.name, node.name))
            continue
        fields = _fields(node)
        for model, signatures in FIELD_SIGNATURES.items():
            if any(signature <= fields for signature in signatures):
                found.append((node.name, model))
                break
    return found


def _sweep() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == MODEL_MODULE:
            continue
        module = path.relative_to(PACKAGE).as_posix()
        for name, model in second_models(path.read_text(encoding="utf-8")):
            found[f"{module}:{name}"] = model
    return found


def test_the_model_module_defines_the_models() -> None:
    """The guard is worth nothing if the thing it protects is not where it looks."""
    defined = {name for name, _ in second_models(MODEL_MODULE.read_text(encoding="utf-8"))}
    assert {
        "Table",
        "Column",
        "Constraint",
        "Index",
        "EnumType",
        "Sequence",
        "Routine",
        "View",
    } <= (defined)


def test_the_check_sees_both_shapes() -> None:
    """Seen red on a class named like a model, and on one that only carries its fields."""
    source = """
class Table:
    name: str

class ColumnRow:
    name: str
    nullable: bool

class Settings:
    name: str
    enabled: bool
"""
    assert second_models(source) == [("Table", "Table"), ("ColumnRow", "Column")]


def test_no_second_model_of_a_schema_object() -> None:
    offenders = sorted(
        f"{site} (a {model})" for site, model in _sweep().items() if site not in ALLOWED
    )
    assert offenders == [], (
        "a second model of a schema object, outside core/schema_model.py:\n  "
        + "\n  ".join(offenders)
        + "\nUse the model, or add the class to ALLOWED with the different question it answers."
    )


def test_the_allow_list_is_current() -> None:
    present = set(_sweep())
    stale = sorted(site for site in ALLOWED if site not in present)
    assert stale == [], f"allow-list entries with nothing left to allow: {stale}"


def test_every_allowed_class_states_a_reason() -> None:
    assert all(reason.strip() for reason in ALLOWED.values())
