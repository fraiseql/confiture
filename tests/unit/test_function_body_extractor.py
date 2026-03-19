"""Unit tests for FunctionSignatureParser.parse_with_bodies()."""

from confiture.core.function_signature_parser import FunctionSignatureParser

SIMPLE_FUNCTION = """
CREATE OR REPLACE FUNCTION public.add_one(n integer)
RETURNS integer
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN n + 1;
END;
$$;
"""

NAMED_DOLLAR_QUOTE = """
CREATE OR REPLACE FUNCTION core.compute(x bigint)
RETURNS bigint
LANGUAGE plpgsql
AS $func$
BEGIN
  RETURN x * 2;
END;
$func$;
"""

C_FUNCTION = """
CREATE FUNCTION pg_catalog.int4in(cstring)
RETURNS integer
LANGUAGE c STRICT IMMUTABLE
AS '$libdir/int.so', 'int4in';
"""

INTERNAL_FUNCTION = """
CREATE FUNCTION pg_catalog.int4larger(integer, integer)
RETURNS integer
LANGUAGE internal IMMUTABLE STRICT
AS 'int4larger';
"""

TWO_FUNCTIONS = """
CREATE FUNCTION public.fn_a(x int) RETURNS int LANGUAGE sql AS $$
  SELECT x + 1;
$$;

CREATE FUNCTION public.fn_b(y text) RETURNS text LANGUAGE sql AS $$
  SELECT upper(y);
$$;
"""


# ---------------------------------------------------------------------------
# Cycle 1: Basic $$ body extraction
# ---------------------------------------------------------------------------


def test_parse_with_bodies_returns_signature_and_body():
    parser = FunctionSignatureParser()
    results = parser.parse_with_bodies(SIMPLE_FUNCTION)
    assert len(results) == 1
    sig, body = results[0]
    assert sig.schema == "public"
    assert sig.name == "add_one"
    assert body is not None
    assert "return n + 1" in body.lower()


def test_parse_with_bodies_signature_matches_parse():
    parser = FunctionSignatureParser()
    sigs_only = parser.parse(SIMPLE_FUNCTION)
    results = parser.parse_with_bodies(SIMPLE_FUNCTION)
    assert len(results) == len(sigs_only)
    for (sig, _), expected in zip(results, sigs_only, strict=True):
        assert sig == expected


# ---------------------------------------------------------------------------
# Cycle 2: Named dollar-quote ($func$, $body$, etc.)
# ---------------------------------------------------------------------------


def test_named_dollar_quote_body_extracted():
    parser = FunctionSignatureParser()
    results = parser.parse_with_bodies(NAMED_DOLLAR_QUOTE)
    assert len(results) == 1
    sig, body = results[0]
    assert sig.name == "compute"
    assert body is not None
    assert "return x * 2" in body.lower()


# ---------------------------------------------------------------------------
# Cycle 3: Functions without extractable bodies (C / internal)
# ---------------------------------------------------------------------------


def test_c_function_returns_none_body():
    parser = FunctionSignatureParser()
    results = parser.parse_with_bodies(C_FUNCTION)
    assert len(results) == 1
    _, body = results[0]
    assert body is None


def test_internal_function_returns_none_body():
    parser = FunctionSignatureParser()
    results = parser.parse_with_bodies(INTERNAL_FUNCTION)
    assert len(results) == 1
    _, body = results[0]
    assert body is None


# ---------------------------------------------------------------------------
# Cycle 4: Multiple functions in the same SQL block
# ---------------------------------------------------------------------------


def test_multiple_functions_all_extracted():
    parser = FunctionSignatureParser()
    results = parser.parse_with_bodies(TWO_FUNCTIONS)
    assert len(results) == 2
    names = {sig.name for sig, _ in results}
    assert names == {"fn_a", "fn_b"}
    bodies = [body for _, body in results if body is not None]
    assert len(bodies) == 2
    assert any("select x + 1" in b.lower() for b in bodies)
    assert any("select upper(y)" in b.lower() for b in bodies)
