"""Unit tests for FunctionParam, FunctionInfo, and FunctionCatalog models.

No database required — pure model construction and property tests.
"""

import pytest

from confiture.models.function_info import (
    FunctionCatalog,
    FunctionInfo,
    FunctionParam,
    ParamMode,
    Volatility,
)


def _make_func(
    name: str = "my_func",
    schema: str = "public",
    is_procedure: bool = False,
    params: list[FunctionParam] | None = None,
    return_type: str | None = "integer",
) -> FunctionInfo:
    return FunctionInfo(
        schema=schema,
        name=name,
        oid=12345,
        params=params or [],
        return_type=return_type,
        returns_set=False,
        volatility=Volatility.VOLATILE,
        is_procedure=is_procedure,
        language="plpgsql",
        source="BEGIN RETURN 1; END;",
        estimated_cost=100.0,
        comment=None,
    )


class TestParamMode:
    def test_all_modes_defined(self):
        assert ParamMode.IN.value == "IN"
        assert ParamMode.OUT.value == "OUT"
        assert ParamMode.INOUT.value == "INOUT"
        assert ParamMode.VARIADIC.value == "VARIADIC"
        assert ParamMode.TABLE.value == "TABLE"


class TestVolatility:
    def test_all_volatilities_defined(self):
        assert Volatility.IMMUTABLE.value == "IMMUTABLE"
        assert Volatility.STABLE.value == "STABLE"
        assert Volatility.VOLATILE.value == "VOLATILE"


class TestFunctionParam:
    def test_basic_construction(self):
        p = FunctionParam(name="user_id", pg_type="bigint")
        assert p.name == "user_id"
        assert p.pg_type == "bigint"
        assert p.mode == ParamMode.IN
        assert p.has_default is False
        assert p.default_expr is None

    def test_with_default(self):
        p = FunctionParam(name="limit", pg_type="integer", has_default=True, default_expr="10")
        assert p.has_default is True
        assert p.default_expr == "10"

    def test_out_mode(self):
        p = FunctionParam(name="result", pg_type="text", mode=ParamMode.OUT)
        assert p.mode == ParamMode.OUT

    def test_inout_mode(self):
        p = FunctionParam(name="counter", pg_type="integer", mode=ParamMode.INOUT)
        assert p.mode == ParamMode.INOUT

    def test_variadic_mode(self):
        p = FunctionParam(name="items", pg_type="text[]", mode=ParamMode.VARIADIC)
        assert p.mode == ParamMode.VARIADIC


class TestFunctionInfo:
    def test_qualified_name(self):
        func = _make_func(name="get_user", schema="auth")
        assert func.qualified_name == "auth.get_user"

    def test_qualified_name_public(self):
        func = _make_func(name="my_func", schema="public")
        assert func.qualified_name == "public.my_func"

    def test_in_params_filters_correctly(self):
        params = [
            FunctionParam("a", "integer", mode=ParamMode.IN),
            FunctionParam("b", "text", mode=ParamMode.OUT),
            FunctionParam("c", "boolean", mode=ParamMode.INOUT),
            FunctionParam("d", "uuid[]", mode=ParamMode.VARIADIC),
            FunctionParam("e", "text", mode=ParamMode.TABLE),
        ]
        func = _make_func(params=params)
        in_p = func.in_params
        assert len(in_p) == 2
        assert in_p[0].name == "a"
        assert in_p[1].name == "c"

    def test_out_params_filters_correctly(self):
        params = [
            FunctionParam("a", "integer", mode=ParamMode.IN),
            FunctionParam("b", "text", mode=ParamMode.OUT),
            FunctionParam("c", "boolean", mode=ParamMode.TABLE),
        ]
        func = _make_func(params=params)
        out_p = func.out_params
        assert len(out_p) == 2
        assert out_p[0].name == "b"
        assert out_p[1].name == "c"

    def test_no_params(self):
        func = _make_func(params=[])
        assert func.in_params == []
        assert func.out_params == []

    def test_is_procedure_flag(self):
        proc = _make_func(is_procedure=True, return_type=None)
        assert proc.is_procedure is True
        func = _make_func(is_procedure=False)
        assert func.is_procedure is False

    def test_volatility_stored(self):
        func2 = FunctionInfo(
            schema="public",
            name="stable_fn",
            oid=999,
            params=[],
            return_type="text",
            returns_set=False,
            volatility=Volatility.STABLE,
            is_procedure=False,
            language="sql",
            source="SELECT 'hello'",
            estimated_cost=1.0,
        )
        assert func2.volatility == Volatility.STABLE

    def test_returns_set(self):
        func = FunctionInfo(
            schema="public",
            name="get_all",
            oid=111,
            params=[],
            return_type="SETOF users",
            returns_set=True,
            volatility=Volatility.STABLE,
            is_procedure=False,
            language="sql",
            source="SELECT * FROM users",
            estimated_cost=100.0,
        )
        assert func.returns_set is True

    def test_comment_defaults_to_none(self):
        func = _make_func()
        assert func.comment is None

    def test_comment_stored(self):
        func = FunctionInfo(
            schema="public",
            name="documented_fn",
            oid=222,
            params=[],
            return_type="void",
            returns_set=False,
            volatility=Volatility.VOLATILE,
            is_procedure=False,
            language="sql",
            source="SELECT 1",
            estimated_cost=1.0,
            comment="This function does something important.",
        )
        assert func.comment == "This function does something important."


class TestFunctionCatalog:
    def test_empty_catalog(self):
        cat = FunctionCatalog(
            database="mydb",
            schema="public",
            introspected_at="2026-01-01T00:00:00+00:00",
            functions=[],
        )
        assert cat.functions == []
        assert cat.by_name("anything") == []
        assert cat.procedures_only() == []
        assert cat.functions_only() == []

    def test_by_name_returns_matching(self):
        f1 = _make_func(name="foo")
        f2 = _make_func(name="bar")
        f3 = _make_func(name="foo")
        f3 = FunctionInfo(
            schema="public",
            name="foo",
            oid=9999,
            params=[FunctionParam("x", "text")],
            return_type="text",
            returns_set=False,
            volatility=Volatility.VOLATILE,
            is_procedure=False,
            language="sql",
            source="SELECT x",
            estimated_cost=1.0,
        )
        cat = FunctionCatalog(
            database="db", schema="public", introspected_at="now", functions=[f1, f2, f3]
        )
        result = cat.by_name("foo")
        assert len(result) == 2
        assert all(f.name == "foo" for f in result)

    def test_by_name_no_match(self):
        cat = FunctionCatalog(
            database="db", schema="public", introspected_at="now", functions=[_make_func("bar")]
        )
        assert cat.by_name("baz") == []

    def test_procedures_only(self):
        proc = _make_func(name="do_thing", is_procedure=True, return_type=None)
        fn = _make_func(name="get_thing", is_procedure=False)
        cat = FunctionCatalog(
            database="db", schema="public", introspected_at="now", functions=[proc, fn]
        )
        procs = cat.procedures_only()
        assert len(procs) == 1
        assert procs[0].name == "do_thing"

    def test_functions_only(self):
        proc = _make_func(name="do_thing", is_procedure=True, return_type=None)
        fn = _make_func(name="get_thing", is_procedure=False)
        cat = FunctionCatalog(
            database="db", schema="public", introspected_at="now", functions=[proc, fn]
        )
        fns = cat.functions_only()
        assert len(fns) == 1
        assert fns[0].name == "get_thing"

    def test_catalog_metadata(self):
        cat = FunctionCatalog(
            database="production",
            schema="api",
            introspected_at="2026-03-10T12:00:00+00:00",
            functions=[],
        )
        assert cat.database == "production"
        assert cat.schema == "api"
        assert cat.introspected_at == "2026-03-10T12:00:00+00:00"


@pytest.mark.parametrize(
    "pg_type,expected_mode",
    [
        ("integer", ParamMode.IN),
        ("text", ParamMode.IN),
    ],
)
def test_function_param_default_mode(pg_type: str, expected_mode: ParamMode):
    p = FunctionParam(name="p", pg_type=pg_type)
    assert p.mode == expected_mode
