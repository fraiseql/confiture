"""Unit tests for FunctionSignatureParser — both pglast and regex paths."""

from unittest.mock import patch

import pytest

from confiture.core.function_signature_parser import FunctionSignature, FunctionSignatureParser


class TestFunctionSignatureParserRegex:
    """Test the regex fallback path directly via _parse_regex."""

    def setup_method(self):
        self.parser = FunctionSignatureParser()

    def test_parse_simple_function(self):
        sql = "CREATE OR REPLACE FUNCTION public.get_user(p_id INTEGER) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert len(sigs) == 1
        assert sigs[0].name == "get_user"
        assert sigs[0].schema == "public"
        assert sigs[0].param_types == ("integer",)

    def test_parse_unqualified_schema_defaults_to_public(self):
        sql = "CREATE FUNCTION my_func(x TEXT) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert len(sigs) == 1
        assert sigs[0].schema == "public"
        assert sigs[0].name == "my_func"

    def test_parse_multiple_params(self):
        sql = "CREATE FUNCTION f(a INTEGER, b TEXT, c UUID) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert len(sigs) == 1
        assert sigs[0].param_types == ("integer", "text", "uuid")

    def test_parse_no_params(self):
        sql = "CREATE FUNCTION ping() RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert len(sigs) == 1
        assert sigs[0].param_types == ()

    def test_parse_procedure(self):
        sql = "CREATE PROCEDURE do_work(p_id BIGINT) LANGUAGE plpgsql AS $$ BEGIN END $$;"
        sigs = self.parser._parse_regex(sql)
        assert len(sigs) == 1
        assert sigs[0].param_types == ("bigint",)

    def test_normalise_int_aliases(self):
        for alias in ("INT", "INT4", "INTEGER"):
            sql = f"CREATE FUNCTION f(x {alias}) RETURNS void AS $$ $$ LANGUAGE sql;"
            sigs = self.parser._parse_regex(sql)
            assert sigs[0].param_types == ("integer",), f"Failed for alias {alias}"

    def test_normalise_bigint_aliases(self):
        for alias in ("INT8", "BIGINT"):
            sql = f"CREATE FUNCTION f(x {alias}) RETURNS void AS $$ $$ LANGUAGE sql;"
            sigs = self.parser._parse_regex(sql)
            assert sigs[0].param_types == ("bigint",), f"Failed for alias {alias}"

    def test_normalise_bool_aliases(self):
        sql = "CREATE FUNCTION f(x BOOL) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert sigs[0].param_types == ("boolean",)

    def test_normalise_timestamptz(self):
        sql = "CREATE FUNCTION f(x TIMESTAMPTZ) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert sigs[0].param_types == ("timestamp with time zone",)

    def test_parse_multiple_functions_in_file(self):
        sql = """
        CREATE FUNCTION foo(a INTEGER) RETURNS void AS $$ $$ LANGUAGE sql;
        CREATE FUNCTION bar(b TEXT, c UUID) RETURNS void AS $$ $$ LANGUAGE sql;
        """
        sigs = self.parser._parse_regex(sql)
        assert len(sigs) == 2
        names = {s.name for s in sigs}
        assert names == {"foo", "bar"}

    def test_default_values_ignored(self):
        sql = "CREATE FUNCTION f(p integer DEFAULT 0) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert len(sigs) == 1
        assert sigs[0].param_types == ("integer",)

    def test_composite_type_default_with_row_constructor(self):
        # Issue #81: ROW(NULL, NULL, NULL)::type was parsed as 3 extra params
        sql = """CREATE OR REPLACE FUNCTION my_schema.my_func(
            v_ctx my_schema.my_type DEFAULT ROW(NULL, NULL, NULL)::my_schema.my_type,
            dry_run BOOLEAN DEFAULT FALSE
        ) RETURNS void AS $$ BEGIN END; $$ LANGUAGE plpgsql;"""
        sigs = self.parser._parse_regex(sql)
        assert len(sigs) == 1
        assert sigs[0].param_types == ("my_schema.my_type", "boolean")

    def test_nested_parens_in_default_single_param(self):
        sql = "CREATE FUNCTION f(x mytype DEFAULT ROW(NULL, NULL)::mytype) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert len(sigs) == 1
        assert sigs[0].param_types == ("mytype",)

    def test_multiple_params_with_and_without_complex_default(self):
        sql = "CREATE FUNCTION f(a integer, b mytype DEFAULT ROW(1, 2)::mytype, c text DEFAULT 'hi') RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert len(sigs) == 1
        assert sigs[0].param_types == ("integer", "mytype", "text")

    def test_out_param_excluded(self):
        sql = "CREATE FUNCTION f(p_in INTEGER, OUT p_out TEXT) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert len(sigs) == 1
        assert sigs[0].param_types == ("integer",)

    def test_inout_param_included(self):
        sql = "CREATE FUNCTION f(INOUT p_val INTEGER) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert len(sigs) == 1
        assert sigs[0].param_types == ("integer",)


class TestFunctionSignatureParserNormalise:
    """Test _normalise_type directly."""

    def setup_method(self):
        self.parser = FunctionSignatureParser()

    def test_pg_catalog_prefix_stripped(self):
        assert self.parser._normalise_type("pg_catalog.int4") == "integer"

    def test_precision_stripped(self):
        assert self.parser._normalise_type("varchar(255)") == "character varying"
        assert self.parser._normalise_type("numeric(10,2)") == "numeric"

    def test_unknown_type_lowercased(self):
        assert self.parser._normalise_type("JSONB") == "jsonb"

    # Issue #176: array suffix must survive normalisation, and the base type must
    # still be aliased through the suffix so source and live sides stay symmetric.
    def test_array_suffix_preserved(self):
        assert self.parser._normalise_type("text[]") == "text[]"
        assert self.parser._normalise_type("uuid[]") == "uuid[]"

    def test_array_suffix_aliased_base(self):
        assert self.parser._normalise_type("int[]") == "integer[]"
        assert self.parser._normalise_type("int4[]") == "integer[]"
        assert self.parser._normalise_type("varchar[]") == "character varying[]"
        assert self.parser._normalise_type("bigint[]") == "bigint[]"

    def test_array_suffix_with_precision(self):
        assert self.parser._normalise_type("numeric(10,2)[]") == "numeric[]"

    def test_array_suffix_sized_is_unsized(self):
        # PostgreSQL ignores array size; format_type renders text[5] as text[].
        assert self.parser._normalise_type("text[5]") == "text[]"

    def test_multidimensional_array(self):
        assert self.parser._normalise_type("int4[][]") == "integer[][]"

    def test_pg_catalog_array(self):
        assert self.parser._normalise_type("pg_catalog.int4[]") == "integer[]"


class TestFunctionSignatureParserArrays:
    """Array parameter types must round-trip with the ``[]`` suffix on BOTH tiers.

    Regression for issue #176: the pglast path dropped ``[]`` (it read
    ``argType.names`` but ignored ``argType.arrayBounds``), producing false stale
    overloads and a destructive ``DROP FUNCTION`` for functions that exist in both
    the DB and the DDL; the regex path kept ``[]`` but failed to alias the base
    type through the suffix (``int[]`` vs live ``integer[]``).
    """

    def setup_method(self):
        self.parser = FunctionSignatureParser()

    def test_regex_preserves_array_suffix(self):
        sql = "CREATE FUNCTION f(a TEXT, b TEXT[]) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert sigs[0].param_types == ("text", "text[]")

    def test_regex_aliases_base_through_array_suffix(self):
        sql = "CREATE FUNCTION f(a INT[], b VARCHAR[], c NUMERIC(10,2)[]) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert sigs[0].param_types == ("integer[]", "character varying[]", "numeric[]")

    def test_regex_array_with_default_expression(self):
        # The exact shape from issue #176: col TYPE[] DEFAULT ARRAY[]::TYPE[]
        sql = (
            "CREATE FUNCTION f(a text, b text[] DEFAULT ARRAY[]::text[]) "
            "RETURNS void AS $$ $$ LANGUAGE sql;"
        )
        sigs = self.parser._parse_regex(sql)
        assert sigs[0].param_types == ("text", "text[]")

    def test_regex_multidim_array(self):
        sql = "CREATE FUNCTION f(m INT[][]) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser._parse_regex(sql)
        assert sigs[0].param_types == ("integer[][]",)

    def test_pglast_preserves_array_suffix(self):
        # parse() routes to pglast when installed — the production path.
        pytest.importorskip("pglast")
        sql = (
            "CREATE FUNCTION core.build_mutation_response("
            "a text, b text, c uuid, d text, e jsonb, tags text[], g jsonb, h jsonb) "
            "RETURNS void AS $$ $$ LANGUAGE sql;"
        )
        sigs = self.parser.parse(sql)
        assert len(sigs) == 1
        assert sigs[0].param_types == (
            "text",
            "text",
            "uuid",
            "text",
            "jsonb",
            "text[]",
            "jsonb",
            "jsonb",
        )

    def test_pglast_aliases_base_through_array_suffix(self):
        pytest.importorskip("pglast")
        sql = "CREATE FUNCTION f(a INT[], b BIGINT[], c VARCHAR[]) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser.parse(sql)
        assert sigs[0].param_types == ("integer[]", "bigint[]", "character varying[]")

    def test_pglast_multidimensional_array(self):
        pytest.importorskip("pglast")
        sql = "CREATE FUNCTION f(m int[][]) RETURNS void AS $$ $$ LANGUAGE sql;"
        sigs = self.parser.parse(sql)
        assert sigs[0].param_types == ("integer[][]",)


class TestFunctionSignatureKey:
    """Test FunctionSignature helper methods."""

    def test_signature_key(self):
        sig = FunctionSignature("public", "get_user", ("integer", "text"))
        assert sig.signature_key() == "public.get_user(integer,text)"

    def test_function_key(self):
        sig = FunctionSignature("public", "get_user", ("integer",))
        assert sig.function_key() == "public.get_user"

    def test_signature_key_no_params(self):
        sig = FunctionSignature("public", "ping", ())
        assert sig.signature_key() == "public.ping()"


class TestFunctionSignatureParserDispatch:
    """Test that parse() routes to pglast when available, regex otherwise."""

    def test_falls_back_to_regex_when_pglast_unavailable(self):
        sql = "CREATE FUNCTION public.f(x INTEGER) RETURNS void AS $$ $$ LANGUAGE sql;"
        with patch.dict("sys.modules", {"pglast": None}):
            parser = FunctionSignatureParser()
            sigs = parser.parse(sql)
        assert len(sigs) == 1
        assert sigs[0].param_types == ("integer",)
