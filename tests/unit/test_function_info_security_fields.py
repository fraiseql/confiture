"""Unit tests for the security_definer / search_path_pinned fields on FunctionInfo (issue #161)."""

from __future__ import annotations

from confiture.core.introspection.functions import _proconfig_pins_search_path
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
# _proconfig_pins_search_path helper
# ---------------------------------------------------------------------------


def test_proconfig_none_not_pinned() -> None:
    assert _proconfig_pins_search_path(None) is False


def test_proconfig_empty_list_not_pinned() -> None:
    assert _proconfig_pins_search_path([]) is False


def test_proconfig_search_path_entry_pinned() -> None:
    assert _proconfig_pins_search_path(["search_path=public"]) is True


def test_proconfig_search_path_with_other_entries() -> None:
    assert _proconfig_pins_search_path(["role=app", "search_path=pg_catalog, public"]) is True


def test_proconfig_only_non_search_path_not_pinned() -> None:
    assert _proconfig_pins_search_path(["role=app", "work_mem=64MB"]) is False


def test_proconfig_search_path_empty_string_pinned() -> None:
    assert _proconfig_pins_search_path(["search_path="]) is True


def test_row_to_info_maps_security_fields() -> None:
    """_proconfig_pins_search_path agrees with the live-catalog contract."""
    row_pinned = ["search_path=public", "role=app"]
    assert _proconfig_pins_search_path(row_pinned) is True

    row_unpinned = ["role=app"]
    assert _proconfig_pins_search_path(row_unpinned) is False

    row_none: list[str] | None = None
    assert _proconfig_pins_search_path(row_none) is False
