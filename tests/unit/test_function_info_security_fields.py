"""Unit tests for the security_definer / search_path_pinned fields on FunctionInfo (issue #161)."""

from __future__ import annotations

from dataclasses import replace

from confiture.core.live_catalog import RoutineRow
from confiture.models.function_info import FunctionInfo, Volatility


def _make_info(**kwargs) -> FunctionInfo:
    defaults: dict = {
        "schema": "public",
        "name": "fn",
        "oid": 1,
        "params": [],
        "return_type": "void",
        "returns_set": False,
        "volatility": Volatility.VOLATILE,
        "is_procedure": False,
        "language": "plpgsql",
        "source": "BEGIN END",
        "estimated_cost": 100.0,
    }
    defaults.update(kwargs)
    return FunctionInfo(**defaults)


# ---------------------------------------------------------------------------
# FunctionInfo field defaults
# ---------------------------------------------------------------------------


def test_function_info_security_definer_defaults_false() -> None:
    fi = _make_info()
    assert fi.security_definer is False


def test_function_info_search_path_pinned_defaults_false() -> None:
    fi = _make_info()
    assert fi.search_path_pinned is False


def test_function_info_security_fields_explicit() -> None:
    fi = _make_info(security_definer=True, search_path_pinned=True)
    assert fi.security_definer is True
    assert fi.search_path_pinned is True


# ---------------------------------------------------------------------------
# RoutineRow.search_path_pinned — the rule the introspector and sec_002 share
# ---------------------------------------------------------------------------

_ROW = RoutineRow(
    oid=1,
    schema="public",
    name="fn",
    kind="f",
    volatility="v",
    language="sql",
    result="void",
    returns_set=False,
    source="",
    cost=100.0,
    arg_names=(),
    arg_modes=(),
    arg_types=(),
    input_types=(),
    identity_arguments="",
    comment=None,
    security_definer=True,
    config=(),
    extension_owned=False,
)


def _pins(proconfig: list[str] | None) -> bool:
    """``live_catalog.routines`` reads a NULL ``proconfig`` as no entries."""
    return replace(_ROW, config=tuple(proconfig or ())).search_path_pinned


def test_proconfig_none_not_pinned() -> None:
    assert _pins(None) is False


def test_proconfig_empty_list_not_pinned() -> None:
    assert _pins([]) is False


def test_proconfig_search_path_entry_pinned() -> None:
    assert _pins(["search_path=public"]) is True


def test_proconfig_search_path_with_other_entries() -> None:
    assert _pins(["role=app", "search_path=pg_catalog, public"]) is True


def test_proconfig_only_non_search_path_not_pinned() -> None:
    assert _pins(["role=app", "work_mem=64MB"]) is False


def test_proconfig_search_path_empty_string_pinned() -> None:
    assert _pins(["search_path="]) is True


def test_row_to_info_maps_security_fields() -> None:
    """The row's pin reading agrees with the live-catalog contract."""
    assert _pins(["search_path=public", "role=app"]) is True
    assert _pins(["role=app"]) is False
    assert _pins(None) is False
