"""No ``DriftType`` may be published that nothing can emit (#303).

``default_mismatch``, ``missing_constraint`` and ``extra_constraint`` were
declared in ``DriftType`` and published in
``_common.schema.json#/$defs/DriftItem`` while **nothing in the package
constructed them**. An agent reading the published enum writes a handler for
``missing_constraint`` that can never fire; a reader who trusts the enum learns
that confiture compares constraints, and it does not.

`DriftType` parity with the published enum is
``tests/unit/json_schemas/test_drift_types_are_published.py``. This guard asks
the harder question: does any module actually *construct* each member?

An unemitted member is allowed with a reason, and the reason has to say what it
would take. Shrinking a published enum breaks a consumer with an exhaustive
``match``, so a member that cannot be emitted yet is kept, documented and filed —
not deleted.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import confiture
from confiture.core.drift import DriftType

PACKAGE = Path(confiture.__file__).resolve().parent

#: Members nothing constructs, with what it would take to emit them. The reason
#: is the deliverable: a hole someone decided on is a decision, and a hole nobody
#: noticed is the defect this guard exists to prevent. Empty since drift compares
#: the schema model on both sides: its constraints and its defaults are compared.
UNEMITTED: dict[str, str] = {}


def _constructed_members() -> set[str]:
    """Every ``DriftType.<NAME>`` the package names in a value position."""
    found: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - the package parses
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "DriftType"
            ):
                found.add(node.attr)
    return found


CONSTRUCTED = _constructed_members()
MEMBERS = {member.name: member.value for member in DriftType}


def test_the_walker_still_finds_something() -> None:
    """A floor: if this is empty, the AST predicate stopped matching."""
    assert "MISSING_TABLE" in CONSTRUCTED


@pytest.mark.parametrize("name", sorted(MEMBERS))
def test_every_drift_type_is_constructed_or_reasoned(name: str) -> None:
    value = MEMBERS[name]
    if name in CONSTRUCTED:
        assert value not in UNEMITTED, (
            f"{value} is constructed, so its UNEMITTED entry is a reason with "
            f"nothing left to explain"
        )
        return
    assert value in UNEMITTED, (
        f"DriftType.{name} is published in the DriftItem enum and no module "
        f"constructs it. Emit it, or record in UNEMITTED what it would take."
    )


def test_every_reason_says_what_it_would_take() -> None:
    thin = sorted(value for value, reason in UNEMITTED.items() if len(reason.split()) < 10)
    assert thin == [], f"reasons too thin to be reasons: {thin}"


def test_the_unemitted_list_names_real_members() -> None:
    assert sorted(set(UNEMITTED) - set(MEMBERS.values())) == []
