"""Unit tests for FunctionSignatureParser — both pglast and regex paths."""

from confiture.core.function_signature_parser import FunctionSignature, FunctionSignatureParser


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
