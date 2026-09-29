"""One relation reference: a relation one object names is two parts, never split text (#478).

PostgreSQL accepts a dot inside a quoted name (``app."a.b"``), so ``schema.name``
text cannot be taken apart again: its last dot may be the name's own. The model
carries a relation another object names — a foreign key's target, an index's
table, a partition's parent, the table a change is on — as
:class:`~confiture.core.schema_model.RelationName`, filled from the parser's and
the catalog's two parts. A name a caller *types* is read by the scanner
(``sql_lexer.name_parts``), which knows where a quoted part ends.

This guard fails on a module that splits text on a dot. Its allow-list is keyed
``module:function`` and each entry says why that text is not a relation's name.
An entry that matches nothing fails too.
"""

from __future__ import annotations

import ast
from pathlib import Path

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent

#: The string methods that take text apart at a separator.
_SPLITTERS = frozenset({"split", "rsplit", "partition", "rpartition"})

#: A type's key and the build's foreign-key mover hold a name as one ``schema.name``
#: string. confiture supports only names that need no quotes (``naming_003`` refuses a
#: dotted one, ``naming_004`` every other that needs quotes, #484), so the last dot of
#: a tree that passes lint is the separator.
_REFUSED_DOT = "one `schema.name` string; a name holding a dot is refused by naming_003"

#: ``module:function`` → why the text it splits on a dot is not a relation's name.
ALLOWED: dict[str, str] = {
    "core/anonymization/plugins/import_checker.py:check_source": (
        "a Python module path (`os.path`): its dots are the language's separators"
    ),
    "core/idempotency/static_eval/scope.py:_import": (
        "a Python module path bound by `import a.b`: its first part is the name bound"
    ),
    "core/validation/config_validator.py:_validate_migrations_tree": (
        "a migration file name: the version is what precedes its first dot"
    ),
    "core/schema_model.py:_relation_from": (
        "a model wire written before a relation was two parts; the dot inside a name "
        "was already lost when that text was written"
    ),
    "models/lint.py:__str__": (
        "a finding's location label, grouped for a one-line summary; nothing is looked up"
    ),
    "core/large_tables.py:table_of": (
        "a change-set target label (`schema.table.column`) the change set writes itself"
    ),
    "core/drift.py:_ignored": (
        "an `ignore_tables` entry from configuration, matched against drift's own "
        "`schema.table` labels"
    ),
    "core/ledger.py:probe_ledger": "the configured `tracking_table`, `schema.table` or bare",
    "core/ledger.py:find_ledger_relations": "the configured `tracking_table`, `schema.table` or bare",
    "core/ledger.py:split_qualified_table": "the configured `tracking_table`, `schema.table` or bare",
    "testing/fixtures/data_validator.py:get_row_count": (
        "a test fixture's `schema.table` argument, written by the test that calls it"
    ),
    "core/linting/inventory.py:type_key": _REFUSED_DOT,
    "core/type_lattice.py:_schema_and_type": _REFUSED_DOT,
    "core/type_lattice.py:_argument_key": _REFUSED_DOT,
    "core/schema_change.py:_written_ref": _REFUSED_DOT,
}


def _splits_on_a_dot() -> set[str]:
    """``module:function`` of every call that splits text on ``"."``."""
    found: set[str] = set()
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _SPLITTERS
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "."
            ):
                continue
            enclosing = [f for f in functions if f.lineno <= node.lineno <= (f.end_lineno or 0)]
            name = (
                min(enclosing, key=lambda f: (f.end_lineno or 0) - f.lineno).name
                if enclosing
                else "<module>"
            )
            found.add(f"{path.relative_to(PACKAGE).as_posix()}:{name}")
    return found


def test_no_module_splits_a_relation_name_on_a_dot() -> None:
    assert sorted(_splits_on_a_dot() - set(ALLOWED)) == []


def test_every_allowed_split_is_still_there() -> None:
    assert sorted(set(ALLOWED) - _splits_on_a_dot()) == []
