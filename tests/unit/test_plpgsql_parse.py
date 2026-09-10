"""Compiling a PL/pgSQL body with libpg_query, which is wrong twice (#270, #272).

`pglast.parse_plpgsql` is the only thing that reads a PL/pgSQL body, and two
different parts of it hand back nothing where a tree should be.

The **compiler** stubs out PostgreSQL's catalogue. Its `LookupExplicitNamespace`
resolves `pg_catalog` and `public`; every other schema is `Not implemented`, so
a type name carrying one of those qualifiers takes the whole routine down before
a line of its body is read — which is how `build_003` came to skip 78.5 % of the
routines on the schema #270 was filed from, silently.

The **serialiser** writes a trigger function's implicit `TG_*` datums as `{}}`,
one closing brace too many each, so `json.loads` never reaches the tree and
every `RETURNS TRIGGER` and `RETURNS event_trigger` body was unread whatever it
contained (#272).

These tests pin three things. The `REFUSED` and `MIS_SERIALISED` tables are
*reach*: one row per shape, so a shape that stops being read fails the row that
regressed. And one invariant per defect, both of them the reason this module
asks rather than models:

- **a qualifier libpg_query accepts is never blanked** — `app.tv_summary`
  reduced to `tv_summary` is a name `build_003` declines to judge, which is
  #270's silent miss moved one step along;
- **a serialisation that decodes is never edited** — the same three characters
  spell a legitimate implicit `RETURN` in very nearly every body, so a global
  replace breaks the routines that were never broken.

Both defects are **pglast 8's alone**, measured: pglast 6.16 and 7.18 compile
every shape in `REFUSED` and in `STILL_REFUSED` and return a trigger body as
valid JSON, and the `[ast]` extra accepts all three majors. So which facts hold
is discovered by probing this interpreter's libpg_query, never from a version
number — the same "ask the parser" rule the module itself follows, and the one
that will quietly retire these skips if libpg_query ever fixes either.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pglast
import pglast.parser
import pytest

from confiture.core.plpgsql_parse import _STRAY, parse_body

#: The serialiser's name for a fragment of SQL, which is what a body is read for.
_EXPR = "PLpgSQL_expr"

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


#: One row per body whose implicit datums `libpg_query` mis-serialises, with the
#: number of stray closing braces each carries. The count is the shape's, not an
#: implementation detail: it is one per datum PL/pgSQL synthesises, and a row
#: whose number moves is libpg_query changing what it synthesises.
MIS_SERIALISED: dict[str, tuple[str, int]] = {
    "returns trigger": (
        "CREATE FUNCTION app.f() RETURNS TRIGGER LANGUAGE plpgsql AS $$\n"
        "BEGIN\n  PERFORM app.fn_log(NEW.id);\n  RETURN NEW;\nEND; $$",
        10,
    ),
    "returns pg_catalog.trigger": (
        "CREATE FUNCTION app.f() RETURNS pg_catalog.trigger LANGUAGE plpgsql AS $$\n"
        "BEGIN\n  PERFORM app.fn_log(NEW.id);\n  RETURN NEW;\nEND; $$",
        10,
    ),
    "returns event_trigger": (
        "CREATE FUNCTION app.f() RETURNS event_trigger LANGUAGE plpgsql AS $$\n"
        "BEGIN\n  PERFORM app.fn_log();\nEND; $$",
        2,
    ),
}


def _serialisation_is_malformed(statement: str) -> bool:
    """Whether *this* libpg_query writes JSON that does not decode. Probed.

    True on pglast 8, false on 6.16 and 7.18 — which do not serialise the
    implicit datums at all, so their output has nothing to repair.
    """
    try:
        pglast.parse_plpgsql(statement)
    except json.JSONDecodeError:
        return True
    except pglast.parser.ParseError:  # pragma: no cover - a different failure
        return False
    return False


#: Whether *this* libpg_query is the one that mis-serialises a trigger
#: function's implicit `TG_` datums. Probed, not looked up.
STRAY_BRACES = _serialisation_is_malformed(MIS_SERIALISED["returns trigger"][0])

needs_the_strays = pytest.mark.skipif(
    not STRAY_BRACES,
    reason="this libpg_query serialises a trigger function's datums as valid JSON",
)


@needs_the_strays
@pytest.mark.parametrize("shape", sorted(MIS_SERIALISED))
def test_libpg_query_mis_serialises_the_shape_on_its_own(shape: str) -> None:
    """The premise, where it holds. A row that stops raising was fixed upstream."""
    with pytest.raises(json.JSONDecodeError):
        pglast.parse_plpgsql(MIS_SERIALISED[shape][0])


@pytest.mark.parametrize("shape", sorted(MIS_SERIALISED))
def test_every_mis_serialised_shape_compiles(shape: str) -> None:
    statement = MIS_SERIALISED[shape][0]

    assert parse_body(statement, body_at=_as_at(statement)).tree


@needs_the_strays
@pytest.mark.parametrize("shape", sorted(MIS_SERIALISED))
def test_the_repair_deletes_one_brace_per_synthesised_datum(shape: str) -> None:
    statement, strays = MIS_SERIALISED[shape]

    assert parse_body(statement, body_at=_as_at(statement)).repaired == strays


def test_a_repaired_body_still_names_what_it_references() -> None:
    """The point of reading it at all: the fragments come back, qualified."""
    statement = (
        "CREATE FUNCTION app.trg_audit() RETURNS TRIGGER LANGUAGE plpgsql AS $$\n"
        "DECLARE v_x int;\nBEGIN\n"
        "    SELECT id INTO v_x FROM app.tv_audit;\n"
        "    PERFORM app.fn_missing(NEW.id);\n"
        "    RETURN NEW;\nEND; $$"
    )

    found = _queries(parse_body(statement, body_at=_as_at(statement)).tree)

    assert {"SELECT app.fn_missing(NEW.id)", "SELECT id FROM app.tv_audit"} <= found


def _queries(tree: object) -> set[str]:
    """Every ``PLpgSQL_expr`` query string in *tree*, whitespace collapsed.

    Collapsed because ``parse_plpgsql`` blanks the ``INTO`` clause out of the
    fragment it hands back, and the run of spaces where it stood is not a fact
    worth pinning. A *subset* because the majors do not agree on what counts as
    a fragment — ``RETURN NEW`` is a ``PLpgSQL_expr`` on pglast 6 and 7 and a
    datum reference on 8 — and it names nothing either way. What every major
    must agree on is the fragments that name something.
    """
    found: set[str] = set()
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            expr = node.get(_EXPR)
            if isinstance(expr, dict) and expr.get("query"):
                found.add(" ".join(expr["query"].split()))
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found


class TestABlindReplaceIsWhatThisIsNot:
    """The repair is positional because a global one corrupts ordinary bodies.

    `{"PLpgSQL_stmt_return":{}}` — the implicit `RETURN` PL/pgSQL appends to a
    body that falls off its end — is a legitimate `{}}` in the serialisation of
    very nearly every routine. `raw.replace("{}}", "{}")` deletes that brace
    too, and the result does not decode: the shortcut breaks the bodies that
    were never broken.

    So the deletion happens only at the position the JSON decoder stopped at,
    and only when the three characters ending there are the defect. A
    serialisation that decodes never enters the loop, whatever it contains.
    """

    #: An ordinary function with no explicit `RETURN`: one legitimate `{}}`,
    #: no stray, and nothing for this module to do.
    VOID = (
        "CREATE FUNCTION app.f() RETURNS void LANGUAGE plpgsql AS $$\n"
        "BEGIN PERFORM app.fn_log(); END; $$"
    )

    @staticmethod
    def _raw(statement: str) -> str:
        return pglast.parser.parse_plpgsql_json(statement)

    def test_a_well_formed_serialisation_is_never_touched(self) -> None:
        assert parse_body(self.VOID, body_at=_as_at(self.VOID)).repaired == 0

    def test_even_though_it_contains_the_three_characters(self) -> None:
        """The premise: without it the test above proves nothing."""
        assert self._raw(self.VOID).count(_STRAY) == 1

    def test_and_a_blind_replace_would_break_it(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            json.loads(self._raw(self.VOID).replace(_STRAY, "{}"))

    @needs_the_strays
    def test_a_body_carrying_both_keeps_the_legitimate_one(self) -> None:
        """An ``event_trigger``: three occurrences, two of them stray."""
        statement = MIS_SERIALISED["returns event_trigger"][0]

        assert self._raw(statement).count(_STRAY) == 3
        assert parse_body(statement, body_at=_as_at(statement)).repaired == 2

    @needs_the_strays
    def test_and_a_blind_replace_would_break_that_too(self) -> None:
        statement = MIS_SERIALISED["returns event_trigger"][0]

        with pytest.raises(json.JSONDecodeError):
            json.loads(self._raw(statement).replace(_STRAY, "{}"))


class TestADefectThisModuleDoesNotKnow:
    """Anything but the known stray brace raises, so the routine stays named.

    `libpg_query` does not emit these, so they are injected: a serialisation
    broken elsewhere must not be quietly half-decoded into a tree the caller
    then reports findings from. A body that went unread is `degraded`, and the
    silent half-read is exactly the failure #270 was filed on.
    """

    @staticmethod
    def _with_serialisation(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        monkeypatch.setattr(pglast.parser, "parse_plpgsql_json", lambda _statement: raw)

    def test_a_truncated_serialisation_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._with_serialisation(monkeypatch, '[{"PLpgSQL_function":{"datums":[')

        with pytest.raises(json.JSONDecodeError):
            parse_body(ACCEPTED["unqualified type"])

    def test_a_stray_brace_that_is_not_the_defect_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One brace too many, but not after an empty object: not this defect."""
        self._with_serialisation(monkeypatch, '[{"PLpgSQL_function":{"datums":[1}},{}]}]')

        with pytest.raises(json.JSONDecodeError):
            parse_body(ACCEPTED["unqualified type"])

    def test_a_defect_at_the_very_start_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No room for three characters before the error: the slice must not wrap."""
        self._with_serialisation(monkeypatch, "}")

        with pytest.raises(json.JSONDecodeError):
            parse_body(ACCEPTED["unqualified type"])


class TestTheTwoRepairsCompose:
    """A trigger body that also names a schema-qualified type is read.

    The compiler refuses it before serialising anything, so the qualifier is
    blanked first and *then* the serialisation needs repairing — which only
    works because the oracle that tests a blank set asks for a tree rather than
    for the absence of one particular exception.
    """

    STATEMENT = (
        "CREATE FUNCTION app.trg_sync() RETURNS TRIGGER LANGUAGE plpgsql AS $$\n"
        "DECLARE v_res app.mutation_response;\n"
        "BEGIN\n"
        "    SELECT * INTO v_res FROM app.tv_summary;\n"
        "    RETURN NEW;\n"
        "END; $$"
    )

    @needs_the_stub
    def test_the_compiler_refuses_it_outright(self) -> None:
        """The premise: this is a `ParseError`, before any JSON exists."""
        with pytest.raises(pglast.parser.ParseError):
            pglast.parse_plpgsql(self.STATEMENT)

    def test_it_compiles(self) -> None:
        assert parse_body(self.STATEMENT, body_at=_as_at(self.STATEMENT)).tree

    @needs_the_stub
    def test_only_the_declared_type_is_blanked(self) -> None:
        compiled = parse_body(self.STATEMENT, body_at=_as_at(self.STATEMENT))

        assert [self.STATEMENT[s:e] for s, e in compiled.neutralised] == ["app."]
        assert "app.tv_summary" in compiled.text

    @needs_the_strays
    def test_and_the_serialisation_still_needed_repairing(self) -> None:
        assert parse_body(self.STATEMENT, body_at=_as_at(self.STATEMENT)).repaired == 10


class TestARepairedBodyNumbersItsOwnLines:
    """The repair edits the serialisation, never the statement.

    A trigger's `lineno`s are the lines its statements are written on, and the
    caller turns those into file lines. This is the pin against a future
    "reconstruct the datums" that renumbers the tree to match.
    """

    STATEMENT = (
        "CREATE FUNCTION app.trg_audit() RETURNS TRIGGER LANGUAGE plpgsql AS $$\n"
        "DECLARE v_x int;\n"
        "BEGIN\n"
        "    SELECT id INTO v_x FROM app.tv_audit;\n"
        "    PERFORM app.fn_missing(NEW.id);\n"
        "    RETURN NEW;\n"
        "END; $$"
    )

    #: ``{fragment: the body line it is written on}``. Only the fragments that
    #: name something: see :func:`_queries` for why an exact set is not a fact
    #: every major agrees on.
    EXPECTED: ClassVar[dict[str, int]] = {
        "SELECT id FROM app.tv_audit": 4,
        "SELECT app.fn_missing(NEW.id)": 5,
    }

    def test_each_statement_reports_the_body_line_it_is_written_on(self) -> None:
        found = _lines_by_query(parse_body(self.STATEMENT, body_at=_as_at(self.STATEMENT)).tree)

        assert {query: found.get(query) for query in self.EXPECTED} == self.EXPECTED

    def test_the_statement_itself_is_handed_over_unchanged(self) -> None:
        compiled = parse_body(self.STATEMENT, body_at=_as_at(self.STATEMENT))

        assert compiled.text == self.STATEMENT
        assert compiled.neutralised == ()


def _lines_by_query(tree: object) -> dict[str, int]:
    """``{normalised SQL fragment: body line}``, the way the caller reads a tree.

    ``parse_plpgsql`` puts ``lineno`` on the statement and the SQL on a
    ``PLpgSQL_expr`` below it, so the nearest enclosing line travels down —
    the same walk :mod:`confiture.core.linting.references` does.
    """
    found: dict[str, int] = {}
    stack: list[tuple[object, int]] = [(tree, 1)]
    while stack:
        node, line = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key == _EXPR and isinstance(value, dict) and value.get("query"):
                    found[" ".join(value["query"].split())] = line
                elif isinstance(value, dict):
                    stack.append((value, value.get("lineno", line)))
                elif isinstance(value, list):
                    stack.append((value, line))
        elif isinstance(node, list):
            stack.extend((item, line) for item in node)
    return found


#: The repository's own SQL: the shipped examples, the schema it builds itself
#: from, and the fixtures the suites read. Real files rather than a table of
#: shapes, which is where #272 was found — the shapes in this module all
#: reduce to one routine, and "5 of the 8 routines we ship" is the measurement
#: that made it worth fixing.
CORPUS_ROOTS = ("db/schema", "examples", "tests/fixtures")


def _repository() -> Path:
    return Path(__file__).resolve().parents[2]


def _plpgsql_routines() -> list[tuple[str, str]]:
    """``(identity, whole CREATE statement)`` for every plpgsql routine shipped.

    A file this repository cannot parse as SQL is some suite's fixture for
    exactly that and is skipped; a routine inside a file that parses is not.
    """
    found: list[tuple[str, str]] = []
    for name in CORPUS_ROOTS:
        for path in sorted((_repository() / name).rglob("*.sql")):
            text = path.read_text()
            try:
                raws = pglast.parse_sql(text)
            except pglast.parser.ParseError:
                continue
            found.extend(_routines_in(text, raws, path.relative_to(_repository())))
    return found


def _routines_in(text: str, raws: object, path: Path) -> Iterator[tuple[str, str]]:
    for raw in raws or ():  # type: ignore[union-attr]
        statement = raw.stmt
        if type(statement).__name__ != "CreateFunctionStmt":
            continue
        options = {option.defname: option for option in (statement.options or ())}
        language = options.get("language")
        if getattr(getattr(language, "arg", None), "sval", None) != "plpgsql":
            continue
        start = raw.stmt_location or 0
        end = start + raw.stmt_len if raw.stmt_len else len(text)
        name = ".".join(part.sval for part in statement.funcname)
        yield f"{path}:{name}", text[start:end]


def _returns_a_trigger(statement: str) -> bool:
    names = pglast.parse_sql(statement)[0].stmt.returnType.names or ()
    return bool(names) and names[-1].sval in {"trigger", "event_trigger"}


ROUTINES = _plpgsql_routines()


def test_the_corpus_holds_the_shape_this_is_about() -> None:
    """Without this the test below can pass by finding nothing at all."""
    assert [identity for identity, sql in ROUTINES if _returns_a_trigger(sql)]


@pytest.mark.parametrize("identity", [identity for identity, _sql in ROUTINES])
def test_every_plpgsql_routine_in_the_repository_is_read(identity: str) -> None:
    """One row per routine confiture ships, so the one that regressed is named.

    5 of these 8 were unread on 1.7.0, all of them triggers. A row that starts
    failing is a routine `build_003` has stopped checking — either a shape
    worth repairing here, or one worth adding to `STILL_REFUSED` with the
    reason it cannot be.
    """
    statement = dict(ROUTINES)[identity]

    assert parse_body(statement).tree
