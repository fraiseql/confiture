"""One PL/pgSQL fragment reader: every fragment, with the statement it belongs to (#363).

The PL/pgSQL compiler hands back each embedded SQL fragment as a string, and a
string alone does not say how to read it: ``SELECT count(*) FROM t`` is a
statement, ``v > 0`` an expression, ``v := core.x(p)`` an assignment. The
compiler does say it — as the statement and the slot the fragment sits in — so
the reader decides by that, never by trying readings until one parses. Trying
is what dropped every ``v := f(…)``: neither ``v := f()`` nor
``SELECT v := f()`` is SQL, so the assignment contributed nothing.
"""

from __future__ import annotations

import pytest

from confiture.core.plpgsql_fragments import SLOTS, Fragment, Mode, fragments, nodes
from confiture.core.plpgsql_parse import parse_body


def _body(body: str, *, returns: str = "int") -> str:
    return f"CREATE FUNCTION app.f(p int) RETURNS {returns} LANGUAGE plpgsql AS $$\n{body}\n$$;"


def _read(body: str, **kwargs: str) -> list[Fragment]:
    return list(fragments(parse_body(_body(body, **kwargs))))


def _names(fragment: Fragment) -> list[str]:
    """Every function a fragment's tree calls, as written."""
    assert fragment.tree is not None, fragment.finding
    return [
        ".".join(part.sval for part in node.funcname)
        for raw in fragment.tree
        for node in _walk(raw)
        if type(node).__name__ == "FuncCall"
    ]


def _walk(node: object):
    from confiture.core.ddl_walk import walk_nodes

    return walk_nodes(node)


class TestTheIssue:
    """#363's two statements: both calls are read, each with its line."""

    BODY = "DECLARE v int; v_result int;\nBEGIN\n  v_result := core.x(p);\n  v := f(v) + 1;\n  RETURN v;\nEND"

    def test_both_calls_are_read(self) -> None:
        found = [f for f in _read(self.BODY) if f.kind == "PLpgSQL_stmt_assign"]

        assert [_names(f) for f in found] == [["core.x"], ["f"]]

    def test_each_on_its_own_line(self) -> None:
        found = [f for f in _read(self.BODY) if f.kind == "PLpgSQL_stmt_assign"]

        # Body-relative: line 1 is the rest of the line `$$` opens.
        assert [f.line for f in found] == [4, 5]

    def test_the_assignment_names_its_target(self) -> None:
        found = [f for f in _read(self.BODY) if f.kind == "PLpgSQL_stmt_assign"]

        assert [f.target for f in found] == ["v_result", "v"]


class TestKindAndSlot:
    def test_a_fragment_carries_the_statement_and_slot_it_sits_in(self) -> None:
        found = _read(
            "DECLARE v int := g();\nBEGIN\n  IF v > 0 THEN PERFORM h(); END IF;\n"
            "  SELECT count(*) INTO v FROM t;\n  RETURN v + 1;\nEND"
        )

        assert [(f.kind, f.slot, f.mode) for f in found] == [
            ("PLpgSQL_var", "default_val", Mode.EXPRESSION),
            ("PLpgSQL_stmt_if", "cond", Mode.EXPRESSION),
            ("PLpgSQL_stmt_perform", "expr", Mode.STATEMENT),
            ("PLpgSQL_stmt_execsql", "sqlstmt", Mode.STATEMENT),
            ("PLpgSQL_stmt_return", "expr", Mode.EXPRESSION),
        ]

    def test_the_owning_node_travels_with_the_fragment(self) -> None:
        (execsql,) = [
            f
            for f in _read("DECLARE v int;\nBEGIN\n  SELECT 1 INTO v;\n  RETURN v;\nEND")
            if f.kind == "PLpgSQL_stmt_execsql"
        ]

        assert execsql.node.get("into") is True

    def test_nodes_walks_every_plpgsql_node_once(self) -> None:
        compiled = parse_body(
            _body("BEGIN\n  IF p > 0 THEN RAISE EXCEPTION 'x'; END IF;\n  RETURN 1;\nEND")
        )

        kinds = [node.kind for node in nodes(compiled.tree)]

        assert kinds.count("PLpgSQL_stmt_raise") == 1
        assert kinds.count("PLpgSQL_stmt_if") == 1


class TestDynamic:
    def test_only_the_string_executed_is_dynamic(self) -> None:
        found = _read("BEGIN\n  EXECUTE 'SELECT 1' USING u();\n  RETURN 1;\nEND")

        (query, params) = [f for f in found if f.kind == "PLpgSQL_stmt_dynexecute"]
        assert query.dynamic and query.tree is None
        assert not params.dynamic
        assert _names(params) == ["u"]

    def test_a_loop_over_a_dynamic_query_reads_its_body(self) -> None:
        found = _read(
            "DECLARE r record;\nBEGIN\n  FOR r IN EXECUTE 'SELECT 1' LOOP\n"
            "    PERFORM inside();\n  END LOOP;\n  RETURN 1;\nEND"
        )

        (perform,) = [f for f in found if f.kind == "PLpgSQL_stmt_perform"]
        assert not perform.dynamic
        assert _names(perform) == ["inside"]


class TestAssignmentShapes:
    """What the left of `:=` may be, and where the right begins."""

    @pytest.mark.parametrize(
        ("statement", "target"),
        [
            ("r.x := g()", "r.x"),
            ("a[1] := g()", "a[1]"),
            ("a[1:2] := ARRAY[g()]", "a[1:2]"),
            ('"Quoted" := g()', '"Quoted"'),
            ("v = g()", "v"),
            ("v = g() = true", "v"),
        ],
    )
    def test_the_target_is_split_off_and_the_rhs_read(self, statement: str, target: str) -> None:
        found = _read(
            'DECLARE v bool; r record; a int[]; "Quoted" int;\n'
            f"BEGIN\n  {statement};\n  RETURN 1;\nEND"
        )

        (assign,) = [f for f in found if f.kind == "PLpgSQL_stmt_assign"]
        assert assign.target == target
        assert _names(assign) == ["g"]

    def test_an_assignment_token_inside_a_string_does_not_split(self) -> None:
        found = _read("DECLARE v text;\nBEGIN\n  v := g('a := b');\n  RETURN 1;\nEND")

        (assign,) = [f for f in found if f.kind == "PLpgSQL_stmt_assign"]
        assert assign.target == "v"
        assert _names(assign) == ["g"]

    def test_a_node_location_maps_back_into_the_fragment_text(self) -> None:
        found = _read("DECLARE v int;\nBEGIN\n  v :=\n    core.x(p);\n  RETURN v;\nEND")

        (assign,) = [f for f in found if f.kind == "PLpgSQL_stmt_assign"]
        assert assign.tree is not None
        (call,) = [n for raw in assign.tree for n in _walk(raw) if type(n).__name__ == "FuncCall"]
        assert assign.text[assign.text_offset(call.location) :].startswith("core.x(p)")
        assert assign.line_of(call.location) == assign.line + 1


class TestAFragmentThatDoesNotParse:
    def test_is_a_finding_never_dropped(self) -> None:
        fragment = Fragment.read(
            kind="PLpgSQL_stmt_execsql", slot="sqlstmt", text="SELEC 1", line=3, node={}
        )

        assert fragment.tree is None
        assert fragment.finding is not None
        assert "syntax error" in fragment.finding

    def test_an_unknown_slot_is_a_finding(self) -> None:
        fragment = Fragment.read(kind="PLpgSQL_stmt_new", slot="thing", text="1", line=1, node={})

        assert fragment.mode is None
        assert fragment.finding == "no reading for PLpgSQL_stmt_new.thing"

    def test_an_assignment_without_an_assignment_token_is_a_finding(self) -> None:
        fragment = Fragment.read(
            kind="PLpgSQL_stmt_assign", slot="expr", text="f(1)", line=1, node={}
        )

        assert fragment.tree is None
        assert fragment.finding == "no top-level := or = in the assignment"


def test_every_slot_names_a_mode() -> None:
    assert all(isinstance(mode, Mode) for mode in SLOTS.values())


class TestARecordVariablesInitialiser:
    """A ``record`` variable's initialiser is read from the text it is written in (#455).

    libpg_query never serialises a ``PLpgSQL_rec``'s ``default_val``: on every
    pglast ``r record := f()`` comes back as a name and a line, and on pglast 8
    so does every variable of a type the compiler stub cannot resolve
    (``v app.t := f()``). The declaration is on the line the compiler names, so
    the initialiser is read from there; where it cannot be found, the fragment
    is a finding, never a silence.
    """

    def _initialisers(self, body: str) -> list[Fragment]:
        return [f for f in _read(body) if f.slot == "default_val"]

    @pytest.mark.parametrize(
        "declaration",
        [
            "r record := app.fn_x();",
            "r record = app.fn_x();",
            "r record DEFAULT app.fn_x();",
            "r CONSTANT record NOT NULL := app.fn_x();",
            "v t := app.fn_x();",
            "v app.t := app.fn_x();",
            '"R" record := app.fn_x();',
        ],
    )
    def test_the_call_is_read(self, declaration: str) -> None:
        (found,) = self._initialisers(f"DECLARE\n  {declaration}\nBEGIN RETURN 1; END")

        assert (found.text, _names(found), found.line) == ("app.fn_x()", ["app.fn_x"], 3)

    def test_two_on_one_line_are_both_read(self) -> None:
        found = self._initialisers(
            "DECLARE a record := app.f1(); b record := app.f2();\nBEGIN RETURN 1; END"
        )

        assert [(_names(f), f.line) for f in found] == [(["app.f1"], 2), (["app.f2"], 2)]

    def test_a_multi_line_initialiser_keeps_its_lines(self) -> None:
        (found,) = self._initialisers(
            "DECLARE\n  r record :=\n    (SELECT 1\n     FROM app.tb_x);\nBEGIN RETURN 1; END"
        )

        assert found.text == "(SELECT 1\n     FROM app.tb_x)"
        assert found.line == 4
        (raw,) = found.tree or ()
        relation = next(n for n in _walk(raw) if type(n).__name__ == "RangeVar")
        assert found.line_of(relation.location) == 5

    @pytest.mark.parametrize(
        "declaration",
        ["r record;", "r record; -- := app.fn_x()", "r record; s text := ';';"],
    )
    def test_a_record_with_none_contributes_none(self, declaration: str) -> None:
        found = self._initialisers(f"DECLARE\n  {declaration}\nBEGIN RETURN 1; END")

        assert [f.text for f in found if f.kind == "PLpgSQL_rec"] == []

    def test_a_cursor_loops_own_variable_has_none(self) -> None:
        """``FOR r IN c`` declares ``r`` itself: a record on its line, never a finding."""
        found = self._initialisers(
            "DECLARE c CURSOR FOR SELECT 1;\nBEGIN\n  FOR r IN c LOOP NULL; END LOOP;\n"
            "  RETURN 1;\nEND"
        )

        assert [f for f in found if f.kind == "PLpgSQL_rec"] == []

    def test_a_declaration_not_where_the_compiler_says_is_a_finding(self) -> None:
        statement = _body("DECLARE\n  r record := app.fn_x();\nBEGIN RETURN 1; END")
        compiled = parse_body(statement)
        (datums,) = [n.fields for n in nodes(compiled.tree) if n.kind == "PLpgSQL_function"]
        for datum in datums["datums"]:
            if "PLpgSQL_rec" in datum:
                datum["PLpgSQL_rec"]["lineno"] = 4

        (found,) = [f for f in fragments(compiled) if f.kind == "PLpgSQL_rec"]

        assert found.tree is None
        assert found.finding == "record variable r: no declaration on body line 4"
