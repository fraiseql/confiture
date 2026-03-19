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
