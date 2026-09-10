"""Compiling a PL/pgSQL body with libpg_query, which has no catalogue (#270).

`pglast.parse_plpgsql` is the only thing that reads a PL/pgSQL body, and the
`libpg_query` build behind it stubs out PostgreSQL's catalogue. The stub's
`LookupExplicitNamespace` resolves `pg_catalog` and `public`; every other schema
is `Not implemented`. A type name carrying one of those qualifiers therefore
takes the whole routine down before a line of its body is read — which is how
`build_003` came to skip 78.5 % of the routines on the schema #270 was filed
from, silently.

These tests pin two things. The table below is *reach*: one row per shape, so a
shape that stops compiling fails the row that regressed. And the invariant,
which is the reason this module is a parser question rather than a grammar
question: **a qualifier libpg_query accepts is never blanked.** Blanking
`app.tv_summary` in a body would leave an unqualified name, which `build_003`
declines to judge — the same silent miss #270 reports, moved one step along.

The refusal is **pglast 8's alone**, measured: pglast 6.16 and 7.18 compile
every shape in `REFUSED` and in `STILL_REFUSED` without complaint, and the
`[ast]` extra accepts all three majors. So which facts hold is discovered by
probing this interpreter's libpg_query, never from a version number — the same
"ask the parser" rule the module itself follows, and the one that will quietly
retire these skips if libpg_query ever resolves the stub.
"""

from __future__ import annotations

import pglast
import pglast.parser
import pytest

from confiture.core.plpgsql_parse import parse_body

#: Bodies are irrelevant to what the compiler refuses, so every row shares one.
_BODY = "$$ DECLARE r RECORD; BEGIN FOR r IN SELECT id FROM public.t LOOP NULL; END LOOP; END; $$"

#: One row per shape libpg_query refuses. The name is the shape, not the error:
#: the message is `libpg_query`'s and differs across the majors the `[ast]`
#: extra accepts, so no test here asserts its text.
REFUSED: dict[str, str] = {
    "composite parameter": f"CREATE FUNCTION app.f(p app.type_input) RETURNS void LANGUAGE plpgsql AS {_BODY}",
    "composite return": f"CREATE FUNCTION app.f() RETURNS app.resp LANGUAGE plpgsql AS {_BODY}",
    "both": f"CREATE FUNCTION app.f(p app.type_input) RETURNS app.resp LANGUAGE plpgsql AS {_BODY}",
    "setof return": f"CREATE FUNCTION app.f() RETURNS SETOF app.resp LANGUAGE plpgsql AS {_BODY}",
    "returns table": f"CREATE FUNCTION app.f() RETURNS TABLE(x app.resp) LANGUAGE plpgsql AS {_BODY}",
    "procedure": f"CREATE PROCEDURE app.p(p app.type_input) LANGUAGE plpgsql AS {_BODY}",
    "declared variable": (
        "CREATE FUNCTION app.f() RETURNS void LANGUAGE plpgsql AS $$\n"
        "DECLARE v app.resp;\nBEGIN NULL; END; $$"
    ),
    "declared variable in a sub-block": (
        "CREATE FUNCTION app.f() RETURNS void LANGUAGE plpgsql AS $$\n"
        "BEGIN\n  DECLARE v app.resp; BEGIN NULL; END;\nEND; $$"
    ),
}

#: One row per shape libpg_query refuses for a reason that is **not** a schema
#: qualifier, so neutralising one cannot help. An array's element type has to be
#: resolved to name the array type, and an element the stub cannot resolve comes
#: back as `record`; `_record` is a type PL/pgSQL declines. That happens to
#: `public.foo[]` and to a bare `foo[]` exactly as it happens to `app.foo[]`, and
#: telling `foo[]` from `text[]` needs the catalogue nobody here has. It is a
#: real hole in `build_003`'s coverage and, since #270's first half, an audible
#: one: the routine is named in the report's `degraded` entry.
STILL_REFUSED: dict[str, str] = {
    "array of an unresolvable type": f"CREATE FUNCTION app.f(p app.type_input[]) RETURNS void LANGUAGE plpgsql AS {_BODY}",
    "array of an unresolvable public type": f"CREATE FUNCTION app.f(p public.type_input[]) RETURNS void LANGUAGE plpgsql AS {_BODY}",
    "array of an unresolvable unqualified type": f"CREATE FUNCTION app.f(p type_input[]) RETURNS void LANGUAGE plpgsql AS {_BODY}",
}

#: One row per shape libpg_query already accepts. Nothing here should change,
#: and nothing here should cost a neutralising pass.
ACCEPTED: dict[str, str] = {
    "public-qualified type": f"CREATE FUNCTION app.f(p public.type_input) RETURNS void LANGUAGE plpgsql AS {_BODY}",
    "pg_catalog-qualified type": f"CREATE FUNCTION app.f(p pg_catalog.text) RETURNS void LANGUAGE plpgsql AS {_BODY}",
    "unqualified type": f"CREATE FUNCTION app.f(p type_input) RETURNS void LANGUAGE plpgsql AS {_BODY}",
    "qualified rowtype": (
        "CREATE FUNCTION app.f() RETURNS void LANGUAGE plpgsql AS $$\n"
        "DECLARE v app.tbl%ROWTYPE;\nBEGIN NULL; END; $$"
    ),
}


def _as_at(statement: str) -> int:
    """Where the ``AS`` clause begins, the way the caller knows it."""
    return statement.index(" AS $$") + 1


def _refuses(statement: str) -> bool:
    try:
        pglast.parse_plpgsql(statement)
    except pglast.parser.ParseError:
        return True
    return False


#: Whether *this* libpg_query is the one that cannot resolve a schema-qualified
#: type. True on pglast 8, false on 6 and 7. Probed, not looked up.
STUB_REFUSES_QUALIFIED_TYPES = _refuses(REFUSED["composite parameter"])

needs_the_stub = pytest.mark.skipif(
    not STUB_REFUSES_QUALIFIED_TYPES,
    reason="this libpg_query resolves a schema-qualified type, so nothing needs neutralising",
)


@needs_the_stub
@pytest.mark.parametrize("shape", sorted(REFUSED))
def test_libpg_query_refuses_the_shape_on_its_own(shape: str) -> None:
    """The premise, where it holds. A row that stops refusing was fixed upstream."""
    with pytest.raises(pglast.parser.ParseError):
        pglast.parse_plpgsql(REFUSED[shape])


@pytest.mark.parametrize("shape", sorted(REFUSED))
def test_every_refused_shape_compiles(shape: str) -> None:
    statement = REFUSED[shape]

    assert parse_body(statement, body_at=_as_at(statement)).tree


@pytest.mark.parametrize("shape", sorted(ACCEPTED))
def test_an_accepted_shape_is_left_alone(shape: str) -> None:
    """Nothing was rewritten, so nothing can have been lost."""
    statement = ACCEPTED[shape]

    compiled = parse_body(statement, body_at=_as_at(statement))

    assert compiled.neutralised == ()
    assert compiled.text == statement


@needs_the_stub
@pytest.mark.parametrize("shape", sorted(STILL_REFUSED))
def test_a_shape_no_qualifier_explains_still_raises(shape: str) -> None:
    """Refused for a reason blanking cannot address, and said so rather than shrugged.

    The message is `libpg_query`'s and its wording differs across the majors the
    ``[ast]`` extra accepts, so nothing here reads it — only that the caller
    gets the exception it needs to name the routine as unread.
    """
    statement = STILL_REFUSED[shape]

    with pytest.raises(pglast.parser.ParseError):
        parse_body(statement, body_at=_as_at(statement))


#: The shape #270 is filed about, with a reference in every place the guess
#: over-blanks: an initialiser's call and a cursor's query are inside a
#: declaration section, and neither is a type.
MUTATION = """CREATE OR REPLACE FUNCTION app.m_c(pk uuid, input_data app.type_input, payload jsonb)
RETURNS app.mutation_response LANGUAGE plpgsql AS $$
DECLARE
  r RECORD;
  v_res app.mutation_response;
  v_default int := app.fn_default();
  c CURSOR FOR SELECT * FROM app.tv_cursor;
BEGIN
  FOR r IN SELECT id FROM public.tv_c LOOP NULL; END LOOP;
  PERFORM core.fn_log(ctx := NULL);
  SELECT * INTO v_res FROM app.tv_summary;
  RETURN v_res;
END; $$"""


class TestTheInvariant:
    """A qualifier the compiler accepts is never blanked.

    This is the whole reason the decision is the compiler's. `app.tv_summary`
    blanked down to `tv_summary` is a name `build_003` declines to judge without
    a declared search path — so an over-eager rewrite would not lose the
    routine, it would lose the finding, which is #270's failure wearing a
    different hat. The guess deliberately over-blanks; putting each blank back
    is what makes the over-blanking safe.
    """

    @staticmethod
    def _blanked(statement: str) -> list[str]:
        compiled = parse_body(statement, body_at=statement.index(" AS $$") + 1)
        return [statement[start:end] for start, end in compiled.neutralised]

    @needs_the_stub
    def test_only_the_type_qualifiers_are_blanked(self) -> None:
        assert self._blanked(MUTATION) == ["app.", "app.", "app."]

    def test_the_references_keep_their_qualifiers(self) -> None:
        compiled = parse_body(MUTATION, body_at=MUTATION.index(" AS $$") + 1)

        for reference in ("app.fn_default()", "app.tv_cursor", "app.tv_summary", "core.fn_log"):
            assert reference in compiled.text

    @needs_the_stub
    def test_the_three_blanked_spans_are_the_declared_and_signature_types(self) -> None:
        """Named, so a future change that blanks a different three fails here."""
        compiled = parse_body(MUTATION, body_at=MUTATION.index(" AS $$") + 1)
        after = [
            MUTATION[end : end + 20].split(maxsplit=1)[0] for _start, end in compiled.neutralised
        ]

        assert after == ["type_input,", "mutation_response", "mutation_response;"]


class TestTheGuessIsOnlyAHint:
    """Correctness comes from the compiler, so a guess that misses only costs a parse."""

    def test_a_type_the_guess_does_not_look_at_still_compiles(self) -> None:
        """With no ``body_at`` the guess cannot see a declaration at all."""
        statement = (
            "CREATE FUNCTION app.f() RETURNS void LANGUAGE plpgsql AS $$\n"
            "DECLARE v app.resp;\nBEGIN NULL; END; $$"
        )

        assert parse_body(statement).tree

    def test_and_the_references_survive_that_route_too(self) -> None:
        compiled = parse_body(MUTATION)

        for reference in ("app.fn_default()", "app.tv_cursor", "app.tv_summary", "core.fn_log"):
            assert reference in compiled.text


class TestWhatBlankingCannotFix:
    @needs_the_stub
    def test_a_body_wrong_for_another_reason_raises(self) -> None:
        """An undeclared loop variable is the body's problem, not the catalogue's."""
        statement = (
            "CREATE FUNCTION app.f(p app.type_input) RETURNS void LANGUAGE plpgsql AS $$\n"
            "BEGIN FOR r IN SELECT 1 LOOP NULL; END LOOP; END; $$"
        )

        with pytest.raises(pglast.parser.ParseError):
            parse_body(statement, body_at=_as_at(statement))

    @needs_the_stub
    def test_a_statement_with_no_qualifier_at_all_raises_at_once(self) -> None:
        """Nothing to neutralise, so nothing is attempted."""
        statement = (
            "CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $$\n"
            "BEGIN FOR r IN SELECT 1 LOOP NULL; END LOOP; END; $$"
        )

        with pytest.raises(pglast.parser.ParseError):
            parse_body(statement, body_at=_as_at(statement))


class TestLinesDoNotMove:
    """Blanking is spaces, not deletion, and every line number depends on it.

    ``parse_plpgsql`` numbers a body from its own first line and the caller adds
    the body's file line to each. A rewrite that moved one newline would move
    every finding below it, so this is the pin that stops a later "just delete
    the qualifier" tidy-up.
    """

    @staticmethod
    def _linenos(tree: object) -> list[int]:
        found: list[int] = []
        stack = [tree]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                found.extend(v for k, v in node.items() if k == "lineno" and isinstance(v, int))
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        return sorted(found)

    @needs_the_stub
    def test_a_neutralised_body_numbers_its_statements_exactly_as_a_plain_one(self) -> None:
        qualified = MUTATION
        plain = MUTATION.replace("app.type_input", "     type_input").replace(
            "app.mutation_response", "     mutation_response"
        )

        assert self._linenos(
            parse_body(qualified, body_at=_as_at(qualified)).tree
        ) == self._linenos(pglast.parse_plpgsql(plain))

    def test_the_text_handed_over_is_the_same_length(self) -> None:
        compiled = parse_body(MUTATION, body_at=_as_at(MUTATION))

        assert len(compiled.text) == len(MUTATION)
        assert compiled.text.count("\n") == MUTATION.count("\n")


class TestTheLexerDecidesWhatIsAName:
    def test_a_qualified_name_inside_a_string_constant_is_not_a_candidate(self) -> None:
        statement = (
            "CREATE FUNCTION app.f(p app.type_input) RETURNS void LANGUAGE plpgsql AS $$\n"
            "BEGIN EXECUTE 'SELECT * FROM app.hidden'; END; $$"
        )

        assert "app.hidden" in parse_body(statement, body_at=_as_at(statement)).text

    def test_a_qualified_name_inside_a_comment_is_not_a_candidate(self) -> None:
        statement = (
            "CREATE FUNCTION app.f(p app.type_input) RETURNS void LANGUAGE plpgsql AS $$\n"
            "BEGIN\n  -- app.commented\n  NULL;\nEND; $$"
        )

        assert "app.commented" in parse_body(statement, body_at=_as_at(statement)).text
