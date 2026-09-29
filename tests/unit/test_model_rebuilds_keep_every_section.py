"""A function that rebuilds a schema model keeps every section of it.

``SchemaModel`` is rebuilt field by field in a few places — placing unqualified
objects in the default schema, normalising for parity — and a section a rebuild
does not name is silently dropped. Adding ``tviews`` (#504) found two that
dropped it. Each rebuild is fed a model with one object in every section.
"""

from __future__ import annotations

import dataclasses

import pytest

from confiture.core.drift import _in_schema
from confiture.core.schema_model import (
    EnumType,
    Routine,
    SchemaModel,
    Sequence,
    Table,
    Trigger,
    TView,
    View,
    normalise_for_parity,
    ref_for,
    routine_ref,
    trigger_ref,
    tview_ref,
    view_ref,
)

ROUTINE = Routine(name="f", schema="app", kind="function", signature="", signature_key=())
VIEW = View(name="v", schema="app")
TRIGGER = Trigger(name="trg", table="t", schema="app")
TVIEW = TView(name="tv_x", schema="app")

FULL = SchemaModel(
    tables={ref_for("table", "app", "t"): Table(name="t", schema="app")},
    enum_types={ref_for("type", "app", "e"): EnumType(name="e", schema="app", values=("a",))},
    sequences={ref_for("sequence", "app", "s"): Sequence(name="s", schema="app")},
    routines={routine_ref(ROUTINE): (ROUTINE,)},
    views={view_ref(VIEW): VIEW},
    triggers={trigger_ref(TRIGGER): TRIGGER},
    tviews={tview_ref(TVIEW): TVIEW},
)


def test_the_fixture_fills_every_section() -> None:
    assert all(getattr(FULL, f.name) for f in dataclasses.fields(SchemaModel))


@pytest.mark.parametrize(
    "rebuild",
    [lambda m: _in_schema(m, "public"), normalise_for_parity],
    ids=["drift._in_schema", "normalise_for_parity"],
)
def test_a_rebuild_keeps_every_section(rebuild) -> None:
    rebuilt = rebuild(FULL)
    empty = [f.name for f in dataclasses.fields(SchemaModel) if not getattr(rebuilt, f.name)]
    assert empty == []
