"""One object identity: what makes two relations the same relation is decided once.

``SchemaDiffer`` was the last reader of a DDL tree in this repository with no
schema in its identity. The lint inventory keys ``(kind, schema, name)`` with
``public`` folded in (``inventory.object_key``); ``ddl_objects.ObjectRef`` keys
the same way; ``drift.py`` qualifies both sides; ``live_objects`` filters on
schema names. The differ keyed a bare ``t.name`` and discarded
``stmt.relation.schemaname`` at parse time, so inside one ``compare()`` call
``a.v`` and ``b.v`` were two views and ``a.t`` and ``b.t`` were one table — the
same run answering the same question two ways (#313).

It cost a reporter four of 433 tables, permanently invisible to
``migrate validate --require-migration``, and it was destructive in the other
direction: swapping two files' build order, with no schema change at all,
generated ``ALTER TABLE t DROP COLUMN IF EXISTS b``.

This is the fourth instance of one pattern here, and the first three each ended
in a guard — ``test_one_type_canonicaliser`` (#275),
``test_one_path_matcher`` (#256), ``test_one_alter_folder`` (#301). Prose did
not hold: ``ddl_objects.py``'s module docstring already said *"Identity is the
inventory's answer, not a second one"*, and ``differ.py`` disagreed with it for
as long as both existed.

Two checks, because the defect had two shapes.

1. **The fold is not restated.** The literal ``"public"`` beside a schema
   variable belongs to :data:`confiture.core.schema_identity.DEFAULT_SCHEMA` and
   nowhere else. Nine sites in four modules spelled it themselves when this was
   written; all nine now import it. The constant moved out of
   ``core/linting/inventory`` — which decides identity but also imports pglast —
   so a module that needs the fold but not a parser can have it, which is why
   two of those four wrote the word instead.

2. **A relation is not keyed by a bare name.** A dict or set comprehension that
   indexes one of this repository's schema-object models by its ``.name`` alone.
   That is the shape of ``differ.py:662``, ``:940`` and ``:973`` at ``3b12dcce``
   — the three sites #313 is made of, all written the same way. Verified: run
   against that revision's ``differ.py``, :func:`_keyed_by_bare_name` names
   exactly those three and their ``new_`` twins.

Check 2 is narrowed to a **named set of models**, resolved from the iterated
collection's attribute name or from the enclosing function's parameter
annotation. Narrow and certain beats broad and disabled: an index or a
constraint keyed by bare name *within one table* is correct and must not be
flagged, and an AST cannot tell those apart by shape alone.
"""

from __future__ import annotations

import ast
from functools import cache
from pathlib import Path

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent
IDENTITY_MODULE = PACKAGE / "core" / "schema_identity.py"

#: The models whose identity is ``(schema, name)`` rather than ``name``.
MODELS = frozenset(
    {
        "Table",
        "EnumType",
        "Sequence",
        "SchemaObject",
        "ObjectRef",
        "DDLObject",
        # The schema model's routine, view and trigger.
        "Routine",
        "View",
        "Trigger",
    }
)

#: Attributes holding a schema-level collection of those models. A ``Table``'s
#: own ``indexes`` / ``foreign_keys`` are deliberately absent: they *are* keyed
#: by bare name, correctly, because the comparison is already scoped to one table.
#: ``SchemaModel`` names its collections the same way, and holds them as mappings
#: keyed by ``ObjectRef`` — so iterating one goes through ``.values()``, which
#: :func:`_collection` sees through.
COLLECTION_ATTRS = frozenset({"tables", "enum_types", "sequences"})

NAME_ATTRS = frozenset({"name", "relname"})

#: Modules that spell a default schema of their own, with the reason. Empty:
#: every site imports :data:`DEFAULT_SCHEMA`. An entry here must name a
#: *different* question, and one that matches nothing fails the test below.
ALLOWED_FOLDS: dict[str, str] = {}

#: Modules that key a schema-object model by a bare name, with the reason. Empty
#: for the same reason. See :data:`KNOWN_LATENT` for what this check cannot see.
ALLOWED_KEYS: dict[str, str] = {}

#: An instance of the same defect that this guard's shape cannot reach, named
#: rather than silently absent. ``_shape`` is asserted to still be present, so
#: the note fails rather than going stale if the code is fixed or rewritten.
#:
#: Empty since #317 fixed the one entry that lived here — prep-seed level 2's
#: ``"prep_seed" in str(sql_file)``. The table stays, because the next defect
#: this guard's shape cannot see has to be written down rather than implied.
KNOWN_LATENT: dict[str, tuple[str, str]] = {}


def _folds_public(path: Path) -> list[int]:
    """Lines where a module spells its own default schema."""
    return [
        node.lineno
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.BoolOp)
        and isinstance(node.op, ast.Or)
        and any(isinstance(v, ast.Constant) and v.value == "public" for v in node.values)
    ]


def _model_in(annotation: ast.expr | None) -> str | None:
    """The model an annotation names: ``list[EnumType]`` -> ``EnumType``."""
    if annotation is None:
        return None
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name) and node.id in MODELS:
            return node.id
        if isinstance(node, ast.Attribute) and node.attr in MODELS:
            return node.attr
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                inner = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                continue
            found = _model_in(inner)
            if found:
                return found
    return None


def _scopes(tree: ast.Module):
    """Every scope, with the parameters it declares as holding schema objects."""
    yield tree, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            args = node.args
            params = {
                arg.arg: model
                for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)
                if (model := _model_in(arg.annotation))
            }
            yield node, params


def _collection(iterated: ast.expr) -> ast.expr:
    """What a comprehension iterates, seen through a mapping's ``.values()``."""
    if (
        isinstance(iterated, ast.Call)
        and isinstance(iterated.func, ast.Attribute)
        and iterated.func.attr == "values"
        and not iterated.args
    ):
        return iterated.func.value
    return iterated


def _keyed_by_bare_name(source: str) -> list[int]:
    """Lines of every ``{x.name: x for x in <schema objects>}`` in one module."""
    tree = ast.parse(source)
    found: set[int] = set()
    for scope, params in _scopes(tree):
        for node in ast.walk(scope):
            if not isinstance(node, ast.DictComp | ast.SetComp):
                continue
            key = node.key if isinstance(node, ast.DictComp) else node.elt
            if not (isinstance(key, ast.Attribute) and key.attr in NAME_ATTRS):
                continue
            if not isinstance(key.value, ast.Name):
                continue
            for gen in node.generators:
                if not isinstance(gen.target, ast.Name) or key.value.id != gen.target.id:
                    continue
                iterated = _collection(gen.iter)
                names_a_collection = (
                    isinstance(iterated, ast.Attribute) and iterated.attr in COLLECTION_ATTRS
                ) or (isinstance(iterated, ast.Name) and iterated.id in params)
                if names_a_collection:
                    found.add(node.lineno)
    return sorted(found)


def _keys_bare(path: Path) -> list[int]:
    return _keyed_by_bare_name(path.read_text(encoding="utf-8"))


@cache
def _sweep(predicate) -> dict[str, tuple[int, ...]]:
    """Every module the predicate matches. Cached: four tests ask the same two questions."""
    found: dict[str, tuple[int, ...]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == IDENTITY_MODULE:
            continue
        lines = predicate(path)
        if lines:
            found[path.relative_to(PACKAGE).as_posix()] = tuple(lines)
    return found


# ---------------------------------------------------------------------------
# Check 1 — the fold is not restated
# ---------------------------------------------------------------------------


def test_the_identity_module_still_holds_the_default() -> None:
    """The guard is worth nothing if the thing it protects moved."""
    from confiture.core.schema_identity import DEFAULT_SCHEMA

    assert DEFAULT_SCHEMA == "public"


def test_the_inventory_uses_the_shared_default() -> None:
    """``inventory.object_key`` is where identity is decided; it must not re-spell it."""
    from confiture.core.linting.inventory import DEFAULT_SCHEMA as inventory_default
    from confiture.core.schema_identity import DEFAULT_SCHEMA

    assert inventory_default is DEFAULT_SCHEMA


def test_no_module_spells_its_own_default_schema() -> None:
    offenders = [
        f"{module}:{line}"
        for module, lines in _sweep(_folds_public).items()
        if module not in ALLOWED_FOLDS
        for line in lines
    ]
    assert offenders == [], (
        "a default schema spelled outside core/schema_identity.py:\n  " + "\n  ".join(offenders)
    )


def test_the_fold_allow_list_is_current() -> None:
    present = set(_sweep(_folds_public))
    stale = sorted(module for module in ALLOWED_FOLDS if module not in present)
    assert stale == [], f"allow-list entries with nothing left to allow: {stale}"


# ---------------------------------------------------------------------------
# Check 2 — a relation is not keyed by a bare name
# ---------------------------------------------------------------------------


def test_the_check_names_the_sites_it_was_written_for() -> None:
    """Seen red: a guard never seen fail is a guard that does not run.

    The three maps of ``3b12dcce``, reproduced verbatim. If this stops matching,
    the predicate has drifted from the shape #313 was made of.
    """
    source = """
class SchemaDiffer:
    def compare(self, old_schema, new_schema):
        old_table_map = {t.name: t for t in old_schema.tables}
        new_table_map = {t.name: t for t in new_schema.tables}

    def _compare_enum_types(self, old_enums: list[EnumType], new_enums: list[EnumType]):
        old_map = {e.name: e for e in old_enums}

    def _compare_sequences(self, old_seqs: list[Sequence], new_seqs: list[Sequence]):
        old_map = {s.name: s for s in old_seqs}
"""
    assert _keyed_by_bare_name(source) == [4, 5, 8, 11]


def test_the_check_sees_through_a_mapping_of_the_model() -> None:
    """``SchemaModel`` holds its objects in mappings; iterating one is still a sweep."""
    source = """
def f(model):
    return {t.name: t for t in model.tables.values()}
"""
    assert _keyed_by_bare_name(source) == [3]


def test_an_index_keyed_by_bare_name_within_one_table_is_not_flagged() -> None:
    """The comparison is already scoped to one table; the name is the identity there."""
    source = """
def _compare_indexes(self, old_table: Table, new_table: Table):
    return {idx.name: idx for idx in old_table.indexes}
"""
    assert _keyed_by_bare_name(source) == []


def test_no_schema_object_is_keyed_by_a_bare_name() -> None:
    offenders = [
        f"{module}:{line}"
        for module, lines in _sweep(_keys_bare).items()
        if module not in ALLOWED_KEYS
        for line in lines
    ]
    assert offenders == [], (
        "schema objects keyed by a bare name (two schemas collapse to one):\n  "
        + "\n  ".join(offenders)
    )


def test_the_key_allow_list_is_current() -> None:
    present = set(_sweep(_keys_bare))
    stale = sorted(module for module in ALLOWED_KEYS if module not in present)
    assert stale == [], f"allow-list entries with nothing left to allow: {stale}"


def test_the_known_latent_instances_are_still_there() -> None:
    """A note about code that changed is worse than no note."""
    for module, (shape, _reason) in KNOWN_LATENT.items():
        text = (PACKAGE / module).read_text(encoding="utf-8")
        assert shape in text, (
            f"{module} no longer contains {shape!r}; either it was fixed — remove the "
            "KNOWN_LATENT entry — or it was rewritten and the note now describes nothing"
        )
