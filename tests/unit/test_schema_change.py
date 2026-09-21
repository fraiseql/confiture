"""The differ emits the change union and nothing else, and every kind is reachable.

``SchemaDiffer.compare`` built ``SchemaChange(type="ADD_TABLE", details={...})`` — a
string and a dict every reader had to spell alike. It now builds one variant of
``core/schema_change.SchemaChange`` per difference. ``tests/fixtures/every_change``
is a pair of trees whose diff is every kind once, so a kind the differ can no
longer reach, or a variant nothing emits, is a failure here rather than a
serialiser branch nobody runs.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

import confiture
from confiture.core.differ import SchemaDiffer
from confiture.core.schema_change import KINDS, SchemaChange, SchemaDiff
from confiture.models.warnings import BuildWarning

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "every_change"
PACKAGE = Path(confiture.__file__).resolve().parent


def _changes(old: str, new: str) -> list[SchemaChange]:
    return SchemaDiffer().compare(old, new).changes


@pytest.mark.parametrize(
    ("old", "new"),
    [("", "old.sql"), ("", "new.sql"), ("old.sql", "new.sql"), ("new.sql", "old.sql")],
)
def test_every_emitted_change_is_a_variant(old: str, new: str) -> None:
    read = {name: (FIXTURES / name).read_text() if name else "" for name in (old, new)}
    changes = _changes(read[old], read[new])
    assert changes
    assert all(type(change) in KINDS for change in changes), [type(c) for c in changes]


def test_the_fixture_pair_emits_every_kind_once() -> None:
    changes = _changes((FIXTURES / "old.sql").read_text(), (FIXTURES / "new.sql").read_text())
    assert Counter(type(change) for change in changes) == dict.fromkeys(KINDS, 1)


def test_a_duplicate_is_a_warning_not_a_change() -> None:
    """``DIFFER_402`` says the diff read a collapsed tree; a collapse is not a difference (#313)."""
    diff = SchemaDiffer().compare("", "CREATE TABLE t (a INT); CREATE TABLE t (a INT);")
    assert isinstance(diff, SchemaDiff)
    assert [w.code for w in diff.warnings] == ["DIFFER_402"]
    assert not any(isinstance(change, BuildWarning) for change in diff.changes)


def _classes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def test_no_variant_shares_a_name_with_a_replica_operation() -> None:
    """Two taxonomies, two vocabularies.

    ``core/replica/classifier.py`` names what a *migration file* does, in the
    imperative (``AddColumn``, ``DropObject``); a variant names a *difference
    between two trees*, as a past participle (``ColumnAdded``, ``ObjectDropped``).
    A shared name would be one word for two things in one package.
    """
    operations = _classes(PACKAGE / "core" / "replica" / "classifier.py")
    assert {"AddColumn", "DropObject", "ReplaceObject"} <= operations
    assert {kind.__name__ for kind in KINDS} & operations == set()
