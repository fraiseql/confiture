"""Unit tests for LiveFunctionCatalog."""

from unittest.mock import MagicMock, patch

from confiture.core.live_function_catalog import LiveFunctionCatalog
from confiture.models.function_info import (
    FunctionCatalog,
    FunctionInfo,
    FunctionParam,
    ParamMode,
    Volatility,
)


def _make_func(
    name: str,
    params: list[FunctionParam],
    schema: str = "public",
) -> FunctionInfo:
    return FunctionInfo(
        schema=schema,
        name=name,
        oid=1,
        params=params,
        return_type="void",
        returns_set=False,
        volatility=Volatility.VOLATILE,
        is_procedure=False,
        language="sql",
        source="",
        estimated_cost=100.0,
    )


def _make_param(pg_type: str, mode: ParamMode = ParamMode.IN) -> FunctionParam:
    return FunctionParam(name="p", pg_type=pg_type, mode=mode)


class TestLiveFunctionCatalog:
    def _mock_conn_and_introspector(self, functions: list[FunctionInfo], schema: str = "public"):
        mock_conn = MagicMock()
        mock_catalog = FunctionCatalog(
            database="test",
            schema=schema,
            introspected_at="2026-01-01T00:00:00",
            functions=functions,
        )
        with patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntrospector:
            MockIntrospector.return_value.introspect.return_value = mock_catalog
            catalog = LiveFunctionCatalog(mock_conn)
            catalog._introspector = MockIntrospector.return_value
        return catalog

    def test_converts_function_info_to_signature(self):
        fn = _make_func("get_user", [_make_param("bigint")])
        catalog = self._mock_conn_and_introspector([fn])
        sigs = catalog.get_signatures()
        assert len(sigs) == 1
        assert sigs[0].name == "get_user"
        assert sigs[0].schema == "public"
        assert sigs[0].param_types == ("bigint",)

    def test_no_functions_returns_empty(self):
        catalog = self._mock_conn_and_introspector([])
        sigs = catalog.get_signatures()
        assert sigs == []

    def test_out_params_excluded_from_signature(self):
        fn = _make_func(
            "f",
            [
                _make_param("integer", ParamMode.IN),
                _make_param("text", ParamMode.OUT),
            ],
        )
        catalog = self._mock_conn_and_introspector([fn])
        sigs = catalog.get_signatures()
        assert len(sigs) == 1
        # OUT param not in sig
        assert sigs[0].param_types == ("integer",)

    def test_inout_param_included(self):
        fn = _make_func("f", [_make_param("integer", ParamMode.INOUT)])
        catalog = self._mock_conn_and_introspector([fn])
        sigs = catalog.get_signatures()
        assert sigs[0].param_types == ("integer",)

    def test_type_normalised(self):
        fn = _make_func("f", [_make_param("int4")])
        catalog = self._mock_conn_and_introspector([fn])
        sigs = catalog.get_signatures()
        assert sigs[0].param_types == ("integer",)

    def test_multiple_schemas_calls_introspect_per_schema(self):
        mock_conn = MagicMock()
        fn1 = _make_func("f", [_make_param("integer")], schema="public")
        fn2 = _make_func("g", [_make_param("text")], schema="auth")

        catalogs = {
            "public": FunctionCatalog("test", "public", "", [fn1]),
            "auth": FunctionCatalog("test", "auth", "", [fn2]),
        }

        with patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntrospector:
            mock_introspector = MockIntrospector.return_value
            mock_introspector.introspect.side_effect = lambda schema: catalogs[schema]
            catalog = LiveFunctionCatalog(mock_conn)
            catalog._introspector = mock_introspector
            sigs = catalog.get_signatures(schemas=["public", "auth"])

        assert mock_introspector.introspect.call_count == 2
        names = {s.name for s in sigs}
        assert names == {"f", "g"}
