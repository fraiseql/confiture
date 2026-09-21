"""``FunctionIntrospector`` over ``live_catalog.routines``: one query, no round trip per type.

The introspector used to resolve each parameter's type with its own
``SELECT format_type(%s, NULL)`` — a round trip per parameter of every routine.
``live_catalog.routines`` spells the types inside the one query, so what is left
here is the mapping from a catalog row to a :class:`FunctionInfo`. What the reader
answers on a real server is ``tests/integration/test_introspection_live.py``.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from confiture.core import live_catalog
from confiture.core.introspection.functions import FunctionIntrospector
from confiture.core.live_catalog import RoutineRow
from confiture.models.function_info import ParamMode, Volatility

ROW = RoutineRow(
    oid=42,
    schema="app",
    name="fn_out",
    kind="f",
    volatility="s",
    language="sql",
    result="record",
    returns_set=False,
    source=" SELECT x, z ",
    cost=100.0,
    arg_names=("x", "y", "z"),
    arg_modes=("i", "o", "b"),
    arg_types=("integer", "integer", "text"),
    input_types=("integer", "text"),
    identity_arguments="x integer, INOUT z text",
    comment="doc",
    security_definer=True,
    config=("search_path=pg_catalog",),
    extension_owned=False,
)


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("testdb",)
    return conn


def stub_routines(monkeypatch: pytest.MonkeyPatch, *rows: RoutineRow) -> list[tuple]:
    calls: list[tuple] = []

    def routines(_conn: object, schemas: list[str], **kwargs: object) -> list[RoutineRow]:
        calls.append((schemas, kwargs))
        return list(rows)

    monkeypatch.setattr(live_catalog, "routines", routines)
    return calls


def test_a_row_becomes_a_function_info(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_routines(monkeypatch, ROW)
    [info] = FunctionIntrospector(_conn()).introspect(schema="app").functions
    assert (info.schema, info.name, info.oid) == ("app", "fn_out", 42)
    assert [(p.name, p.pg_type, p.mode) for p in info.params] == [
        ("x", "integer", ParamMode.IN),
        ("y", "integer", ParamMode.OUT),
        ("z", "text", ParamMode.INOUT),
    ]
    assert (info.return_type, info.returns_set, info.volatility) == (
        "record",
        False,
        Volatility.STABLE,
    )
    assert (info.language, info.source, info.estimated_cost, info.comment) == (
        "sql",
        " SELECT x, z ",
        100.0,
        "doc",
    )
    assert (info.is_procedure, info.security_definer, info.search_path_pinned) == (
        False,
        True,
        True,
    )


def test_no_names_and_no_modes_mean_unnamed_in_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    """The catalog stores no ``proargmodes`` when every argument is ``IN``."""
    stub_routines(monkeypatch, replace(ROW, arg_names=(), arg_modes=(), kind="p", config=()))
    [info] = FunctionIntrospector(_conn()).introspect(schema="app").functions
    assert [(p.name, p.mode) for p in info.params] == [("", ParamMode.IN)] * 3
    assert info.is_procedure is True
    assert info.search_path_pinned is False


def test_a_type_costs_no_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """``current_database()`` is the only statement the introspector runs itself."""
    stub_routines(monkeypatch, ROW, replace(ROW, oid=43, arg_types=("bigint",) * 40))
    conn = _conn()
    FunctionIntrospector(conn).introspect(schema="app")
    cursor = conn.cursor.return_value.__enter__.return_value
    assert [c.args[0] for c in cursor.execute.call_args_list] == ["SELECT current_database()"]


def test_the_filters_reach_the_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = stub_routines(monkeypatch)
    introspector = FunctionIntrospector(_conn())
    introspector.introspect(schema="app", include_triggers=True, name_pattern="fn%")
    introspector.introspect_one("app", "fn_add")
    assert calls == [
        (["app"], {"include_triggers": True, "name_pattern": "fn%"}),
        (["app"], {"include_triggers": False, "name_pattern": "fn_add", "exact_name": True}),
    ]
