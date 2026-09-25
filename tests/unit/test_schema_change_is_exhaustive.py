"""Every kind of schema change is answered for, everywhere a change is read.

``core/schema_change.KINDS`` is closed, and this guard enumerates it: each kind must
have an up rendering and a down rendering (``differ_sql``), a destructive verdict
(``destructive.data_loss_reason``), an accompaniment class
(``git_accompaniment.is_body_change``) and a risk tier (``change_set.diff_tiers``). One sample per kind comes from ``tests/fixtures/every_change``,
the pair whose diff is every kind once, so a kind the differ no longer emits fails
here too.

The ``match`` statements that answer are checked as well: a ``match`` over the union
that ends in anything but ``case _: assert_never(...)`` would let a new kind fall
through to a default nobody chose, which is how the string dispatch it replaced
generated nothing for a change it did not know. And the wire's ``type`` strings —
``"ADD_COLUMN"`` — appear in the serialiser and nowhere else: a reader that compares
them is reading a spelling, not the change.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import confiture
from confiture.core import destructive, git_accompaniment
from confiture.core.change_set.diff_tiers import tier_of
from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.risk_tier import RiskTier
from confiture.core.schema_change import (
    KINDS,
    ColumnChange,
    DefinitionChange,
    EnumOrSequenceChange,
    SchemaChange,
    TableChange,
    TableObjectChange,
)

PACKAGE = Path(confiture.__file__).resolve().parent
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "every_change"
SERIALISER = "core/schema_change.py"

#: Modules that spell a wire type for a reason of their own. A different vocabulary
#: that shares a spelling is not a reader of the wire.
WIRE_SPELLINGS_ALLOWED: dict[str, str] = {
    "core/idempotency/models.py": (
        "PatternType's finding codes (DROP_TABLE, DROP_INDEX, DROP_SEQUENCE) name a "
        "non-idempotent statement in a migration file, not a schema change"
    ),
}


def _samples() -> dict[type[SchemaChange], SchemaChange]:
    old = (FIXTURES / "old.sql").read_text()
    new = (FIXTURES / "new.sql").read_text()
    return {type(change): change for change in SchemaDiffer().compare(old, new).changes}


SAMPLES = _samples()


def _kind_id(kind: type[SchemaChange]) -> str:
    return kind.__name__


def test_the_fixture_holds_a_sample_of_every_kind() -> None:
    assert set(SAMPLES) == set(KINDS)


def test_the_renderer_groups_partition_the_union() -> None:
    groups = [TableChange, ColumnChange, TableObjectChange, EnumOrSequenceChange, DefinitionChange]
    members = [kind for group in groups for kind in group.__args__]
    assert sorted(members, key=_kind_id) == sorted(KINDS, key=_kind_id)


@pytest.mark.parametrize("kind", sorted(KINDS, key=_kind_id), ids=_kind_id)
def test_every_kind_is_answered_for(kind: type[SchemaChange]) -> None:
    change = SAMPLES[kind]
    renderer = DifferSQLGenerator()
    rendered = [renderer.generate_up(change), renderer.generate_down(change)]
    assert all(sql.endswith("\n") for sql in rendered if sql is not None), rendered
    assert destructive.data_loss_reason(change) in (None, "data")
    assert git_accompaniment.is_body_change(change) in (True, False)
    assert isinstance(tier_of(change), RiskTier), f"{kind.__name__} declares no tier"


def _names(pattern: ast.pattern) -> set[str]:
    return {
        node.cls.id
        for node in ast.walk(pattern)
        if isinstance(node, ast.MatchClass) and isinstance(node.cls, ast.Name)
    }


def _closed(match: ast.Match) -> bool:
    last = match.cases[-1]
    if not (isinstance(last.pattern, ast.MatchAs) and last.pattern.pattern is None):
        return False
    body = last.body
    return (
        len(body) == 1
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Call)
        and getattr(body[0].value.func, "id", None) == "assert_never"
    )


def _unclosed_matches(source: str) -> list[int]:
    kinds = {kind.__name__ for kind in KINDS}
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Match)
        and any(_names(case.pattern) & kinds for case in node.cases)
        and not _closed(node)
    ]


def test_every_match_over_the_union_ends_in_assert_never() -> None:
    open_matches = [
        f"{path.relative_to(PACKAGE).as_posix()}:{line}"
        for path in sorted(PACKAGE.rglob("*.py"))
        for line in _unclosed_matches(path.read_text(encoding="utf-8"))
    ]
    assert open_matches == [], (
        "a match over SchemaChange without `case _: assert_never(change)`:\n  "
        + "\n  ".join(open_matches)
    )


def test_the_match_check_sees_a_default_arm() -> None:
    """The guard, seen red: a ``case _: return None`` is a default nobody chose."""
    source = (
        "def f(change):\n"
        "    match change:\n"
        "        case TableAdded():\n"
        "            return 1\n"
        "        case _:\n"
        "            return None\n"
    )
    assert _unclosed_matches(source) == [2]


def _wire_spellings(source: str) -> set[str]:
    wires = {kind.WIRE for kind in KINDS if hasattr(kind, "WIRE")}
    return {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in wires
    }


def test_the_wire_types_are_spelled_only_by_the_serialiser() -> None:
    spelled = {
        rel: sorted(found)
        for path in sorted(PACKAGE.rglob("*.py"))
        if (rel := path.relative_to(PACKAGE).as_posix()) != SERIALISER
        and (found := _wire_spellings(path.read_text(encoding="utf-8")))
    }
    assert set(spelled) == set(WIRE_SPELLINGS_ALLOWED), spelled


def test_the_serialiser_spells_every_fixed_wire_type() -> None:
    assert len(_wire_spellings((PACKAGE / SERIALISER).read_text(encoding="utf-8"))) == 22
