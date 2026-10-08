"""Drift is the one comparison said as findings: ``drift.DRIFT_OF`` answers for every change.

``confiture drift`` once had a comparison of its own beside the differ's, and the
two disagreed (a primary key, a foreign key's action, a default's value were
drift's alone). Now drift asks the differ and says what it answers. This module
holds the table that says it: every variant of the change union is a finding of a
stated kind and severity, or names why drift has none — and every schema drift
kind is reached from it, so none is reported by a comparison of drift's own.
"""

import ast
from pathlib import Path

import confiture
from confiture.core.drift import _OBJECT_DRIFT_TYPES, DRIFT_OF, DriftType
from confiture.core.schema_change import KINDS

DRIFT = Path(confiture.__file__).resolve().parent / "core" / "drift.py"

#: The kinds another detector reports: grants and owners are not schema facts.
_NOT_THE_SCHEMAS = {DriftType.MISSING_GRANT, DriftType.EXTRA_GRANT, DriftType.WRONG_OWNER}


def test_every_change_is_a_finding_or_says_why_not() -> None:
    assert set(DRIFT_OF) == set(KINDS)
    reasons = [why for why in DRIFT_OF.values() if isinstance(why, str)]
    assert all(why.strip() for why in reasons)


def test_every_schema_drift_kind_is_reached_from_the_table() -> None:
    reached = {kind for kind, _ in (v for v in DRIFT_OF.values() if not isinstance(v, str))}
    reached |= {kind for pair in _OBJECT_DRIFT_TYPES.values() for kind in pair}
    # A constraint dropped and added under one name is one finding.
    reached.add(DriftType.CONSTRAINT_MISMATCH)
    assert set(DriftType) - _NOT_THE_SCHEMAS == reached - {None}


def test_drift_compares_nothing_itself() -> None:
    """No ``_compare_*`` and no ``_same_*``: a second comparison is how they disagreed."""
    defined = {
        node.name
        for node in ast.walk(ast.parse(DRIFT.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef)
    }
    assert sorted(n for n in defined if n.startswith(("_compare_", "_same_"))) == []
