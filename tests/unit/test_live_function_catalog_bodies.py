"""Unit tests for LiveFunctionCatalog.get_bodies()."""

from unittest.mock import MagicMock, patch

from confiture.core.live_function_catalog import LiveFunctionCatalog
from confiture.models.function_info import FunctionInfo, FunctionParam, ParamMode, Volatility


def _make_fn_info(
    schema: str,
    name: str,
    param_types: list[str],
    source: str | None,
    language: str = "plpgsql",
) -> FunctionInfo:
    """Build a minimal FunctionInfo for testing."""
    params = [
        FunctionParam(name=f"p{i}", pg_type=t, mode=ParamMode.IN) for i, t in enumerate(param_types)
    ]
    return FunctionInfo(
        schema=schema,
        name=name,
        oid=1000,
        params=params,
        return_type="void",
        returns_set=False,
        volatility=Volatility.VOLATILE,
        is_procedure=False,
        language=language,
        source=source,
        estimated_cost=100.0,
    )


def _catalog_mock(functions: list[FunctionInfo]) -> MagicMock:
    m = MagicMock()
    m.functions = functions
    return m


# ---------------------------------------------------------------------------
# Cycle 1: Basic body retrieval
# ---------------------------------------------------------------------------


def test_get_bodies_returns_body_for_plpgsql():
    conn = MagicMock()
    with patch("confiture.core.live_function_catalog.FunctionIntrospector") as intr_cls:
        intr_cls.return_value.introspect.return_value = _catalog_mock(
            [_make_fn_info("public", "foo", ["integer"], "BEGIN RETURN $1; END;")]
        )
        live = LiveFunctionCatalog(conn)
        bodies = live.get_bodies(schemas=["public"])

    assert "public.foo(integer)" in bodies
    assert bodies["public.foo(integer)"] == "BEGIN RETURN $1; END;"


def test_get_bodies_c_language_returns_none():
    conn = MagicMock()
    with patch("confiture.core.live_function_catalog.FunctionIntrospector") as intr_cls:
        intr_cls.return_value.introspect.return_value = _catalog_mock(
            [_make_fn_info("pg_catalog", "int4in", ["cstring"], "int4in", language="c")]
        )
        live = LiveFunctionCatalog(conn)
        bodies = live.get_bodies(schemas=["pg_catalog"])

    assert bodies.get("pg_catalog.int4in(cstring)") is None


def test_get_bodies_internal_language_returns_none():
    conn = MagicMock()
    with patch("confiture.core.live_function_catalog.FunctionIntrospector") as intr_cls:
        intr_cls.return_value.introspect.return_value = _catalog_mock(
            [
                _make_fn_info(
                    "pg_catalog",
                    "int4larger",
                    ["integer", "integer"],
                    "int4larger",
                    language="internal",
                )
            ]
        )
        live = LiveFunctionCatalog(conn)
        bodies = live.get_bodies(schemas=["pg_catalog"])

    assert bodies.get("pg_catalog.int4larger(integer,integer)") is None


# ---------------------------------------------------------------------------
# Cycle 2: sig_keys filter
# ---------------------------------------------------------------------------


def test_get_bodies_sig_keys_filter():
    conn = MagicMock()
    with patch("confiture.core.live_function_catalog.FunctionIntrospector") as intr_cls:
        intr_cls.return_value.introspect.return_value = _catalog_mock(
            [
                _make_fn_info("public", "foo", ["integer"], "BODY_FOO"),
                _make_fn_info("public", "bar", ["text"], "BODY_BAR"),
            ]
        )
        live = LiveFunctionCatalog(conn)
        bodies = live.get_bodies(
            schemas=["public"],
            sig_keys={"public.foo(integer)"},
        )

    assert "public.foo(integer)" in bodies
    assert "public.bar(text)" not in bodies


# ---------------------------------------------------------------------------
# Cycle 3: Empty result
# ---------------------------------------------------------------------------


def test_get_bodies_empty_when_no_functions():
    conn = MagicMock()
    with patch("confiture.core.live_function_catalog.FunctionIntrospector") as intr_cls:
        intr_cls.return_value.introspect.return_value = _catalog_mock([])
        live = LiveFunctionCatalog(conn)
        bodies = live.get_bodies(schemas=["public"])

    assert bodies == {}


# ---------------------------------------------------------------------------
# Cache behaviour: get_signatures + get_bodies share one DB query
# ---------------------------------------------------------------------------


def test_get_signatures_and_get_bodies_share_one_introspect_call():
    conn = MagicMock()
    with patch("confiture.core.live_function_catalog.FunctionIntrospector") as intr_cls:
        mock_introspector = intr_cls.return_value
        mock_introspector.introspect.return_value = _catalog_mock(
            [_make_fn_info("public", "foo", ["integer"], "SELECT $1;")]
        )
        live = LiveFunctionCatalog(conn)
        live.get_signatures(schemas=["public"])
        live.get_bodies(schemas=["public"])

    # introspect should only be called once due to caching
    assert mock_introspector.introspect.call_count == 1
