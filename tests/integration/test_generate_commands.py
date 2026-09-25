"""``confiture generate pgtap`` and ``generate stubs``, run by their command line.

Both read a live database's routines and write a file for another tool to run:
pgTAP SQL for ``pg_prove``, Python for an application to import. So each test
reads what was written the way that tool would. The pgTAP scaffold is parsed by
PostgreSQL's own parser once the lines ``psql`` would take as meta-commands are
set aside, and it must name the function it tests. The stubs are compiled,
imported, and called against the database they were generated from.

The ``xfail`` tests record defects found while writing this file. Each one
states the command line that shows it.

Every test runs in a database of its own.
"""

from __future__ import annotations

import ast as pyast
import importlib.util
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import psycopg
import pytest
from pglast import ast, parse_sql
from pglast.visitors import Visitor
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.psql_applier import find_meta_commands

pytestmark = pytest.mark.integration

runner = CliRunner()

#: What a command writes to stdout when nothing sets the width: a pipe, CI.
_NO_TERMINAL = {"COLUMNS": "80"}

#: The pgTAP functions a scaffold for routines can call. Taken from pgTAP's
#: ``sql/pgtap.sql.in``: its volatility assertion is ``volatility_is``.
_PGTAP_API = frozenset(
    {
        "plan",
        "finish",
        "ok",
        "has_function",
        "hasnt_function",
        "function_returns",
        "function_lang_is",
        "volatility_is",
        "is_definer",
        "isnt_definer",
        "is_strict",
        "isnt_strict",
        "is_normal_function",
        "is_aggregate",
        "is_window",
        "is_procedure",
    }
)


@pytest.fixture
def database(fresh_database: str) -> str:
    """A database holding two SQL functions: ``add_one`` and ``shout``."""
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(
            "CREATE FUNCTION add_one(n integer) RETURNS integer "
            "LANGUAGE sql IMMUTABLE AS 'SELECT n + 1'"
        )
        conn.execute(
            "CREATE FUNCTION shout(p_word text) RETURNS text "
            "LANGUAGE sql STABLE AS 'SELECT upper(p_word)'"
        )
    return fresh_database


class _Calls(Visitor):
    """Every function call in a tree: its name and its string-literal arguments."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str | None, ...]]] = []

    def visit_FuncCall(self, _ancestors: object, node: ast.FuncCall) -> None:
        args = tuple(
            arg.val.sval
            if isinstance(arg, ast.A_Const) and isinstance(arg.val, ast.String)
            else None
            for arg in node.args or ()
        )
        self.calls.append((node.funcname[-1].sval, args))


def _sql_of(script: str) -> tuple[ast.RawStmt, ...]:
    """The statements of a ``psql`` script: its meta-command lines blanked, the rest parsed."""
    lines = script.split("\n")
    for meta in find_meta_commands(script):
        lines[meta.line - 1] = " " * len(lines[meta.line - 1])
    return parse_sql("\n".join(lines))


def _calls(statements: tuple[ast.RawStmt, ...]) -> list[tuple[str, tuple[str | None, ...]]]:
    visitor = _Calls()
    for statement in statements:
        visitor(statement)
    return visitor.calls


@pytest.fixture
def load_module() -> Iterator[Callable[[Path], ModuleType]]:
    """``load(path) -> module``: import a generated file the way an application would."""
    names: list[str] = []

    def load(path: Path) -> ModuleType:
        name = f"confiture_stubs_{uuid.uuid4().hex[:8]}"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        names.append(name)
        spec.loader.exec_module(module)
        return module

    yield load

    for name in names:
        sys.modules.pop(name, None)


# ── generate pgtap ─────────────────────────────────────────────────────────────


def test_pgtap_writes_sql_that_parses_and_tests_each_function(
    database: str, tmp_path: Path
) -> None:
    out = tmp_path / "tests" / "functions.sql"

    result = runner.invoke(app, ["generate", "pgtap", "--database-url", database, "-o", str(out)])

    assert result.exit_code == 0, result.output
    script = out.read_text()
    assert [meta.text for meta in find_meta_commands(script)] == [
        "\\set ON_ERROR_STOP 1",
        "\\set ON_ERROR_ROLLBACK 1",
    ]
    statements = _sql_of(script)
    calls = _calls(statements)
    assert ("has_function", ("public", "add_one", "Function public.add_one should exist")) in calls
    assert (
        "function_returns",
        ("public", "add_one", "integer", "Function public.add_one should return integer"),
    ) in calls
    assert ("has_function", ("public", "shout", "Function public.shout should exist")) in calls


def test_pgtap_plans_one_test_per_statement(database: str, tmp_path: Path) -> None:
    """``plan(n)`` must equal the tests the file runs, or ``pg_prove`` fails the file."""
    out = tmp_path / "functions.sql"

    result = runner.invoke(app, ["generate", "pgtap", "-d", database, "--output", str(out)])

    assert result.exit_code == 0, result.output
    statements = [raw.stmt for raw in _sql_of(out.read_text())]
    kinds = [type(statement).__name__ for statement in statements]
    assert kinds[0] == "TransactionStmt"
    assert kinds[-1] == "TransactionStmt"
    plan, *tests, finish = statements[1:-1]
    assert _calls((plan,))[0][0] == "plan"
    assert _calls((finish,)) == [("finish", ())]
    assert plan.targetList[0].val.args[0].val.ival == len(tests) == 6


def test_pgtap_include_and_the_opt_out_flags_narrow_the_scaffold(
    database: str, tmp_path: Path
) -> None:
    out = tmp_path / "add_one.sql"

    result = runner.invoke(
        app,
        [
            "generate",
            "pgtap",
            "-d",
            database,
            "--include",
            "add%",
            "--no-volatility",
            "--no-return-type",
            "-o",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    calls = _calls(_sql_of(out.read_text()))
    assert [name for name, _ in calls] == ["plan", "has_function", "finish"]
    assert calls[1][1][:2] == ("public", "add_one")


def test_pgtap_calls_only_functions_pgtap_defines(database: str, tmp_path: Path) -> None:
    out = tmp_path / "functions.sql"

    result = runner.invoke(app, ["generate", "pgtap", "-d", database, "-o", str(out)])

    assert result.exit_code == 0, result.output
    called = {name for name, _ in _calls(_sql_of(out.read_text()))}
    assert called <= _PGTAP_API, sorted(called - _PGTAP_API)


def test_pgtap_on_stdout_is_the_sql_it_would_write(database: str) -> None:
    result = runner.invoke(app, ["generate", "pgtap", "-d", database], env=_NO_TERMINAL)

    assert result.exit_code == 0, result.output
    calls = _calls(_sql_of(result.stdout))
    assert ("has_function", ("public", "add_one", "Function public.add_one should exist")) in calls


# ── generate stubs ─────────────────────────────────────────────────────────────


def test_stubs_write_python_that_compiles_and_calls_the_function(
    database: str, tmp_path: Path, load_module
) -> None:
    out = tmp_path / "db_functions.py"

    result = runner.invoke(app, ["generate", "stubs", "--database-url", database, "-o", str(out)])

    assert result.exit_code == 0, result.output
    source = out.read_text()
    compile(source, str(out), "exec")
    defined = {
        node.name for node in pyast.parse(source).body if isinstance(node, pyast.FunctionDef)
    }
    assert defined == {"add_one", "shout"}
    stubs = load_module(out)
    with psycopg.connect(database) as conn:
        assert stubs.add_one(conn, 41) == 42
        assert stubs.shout(conn, "jam") == "JAM"


def test_stubs_include_keeps_only_the_matching_function(database: str, tmp_path: Path) -> None:
    out = tmp_path / "stubs.py"

    result = runner.invoke(
        app, ["generate", "stubs", "-d", database, "--include", "shout", "-o", str(out)]
    )

    assert result.exit_code == 0, result.output
    tree = pyast.parse(out.read_text())
    assert [node.name for node in tree.body if isinstance(node, pyast.FunctionDef)] == ["shout"]


def test_stubs_for_a_jsonb_function_return_its_model(
    fresh_database: str, tmp_path: Path, load_module
) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(
            "CREATE FUNCTION widget_summary(p_id bigint) RETURNS jsonb LANGUAGE plpgsql "
            "STABLE AS $$ BEGIN RETURN jsonb_build_object('id', p_id, 'label', 'x'); END $$"
        )
    out = tmp_path / "stubs.py"

    result = runner.invoke(app, ["generate", "stubs", "-d", fresh_database, "-o", str(out)])

    assert result.exit_code == 0, result.output
    stubs = load_module(out)
    with psycopg.connect(fresh_database) as conn:
        summary = stubs.widget_summary(conn, 5)
    assert (summary.id, summary.label) == (5, "x")


def test_stubs_dataclass_format_writes_no_pydantic_model(
    fresh_database: str, tmp_path: Path
) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(
            "CREATE FUNCTION widget_summary(p_id bigint) RETURNS jsonb LANGUAGE sql "
            "STABLE AS $$ SELECT jsonb_build_object('id', p_id) $$"
        )
    out = tmp_path / "stubs.py"

    result = runner.invoke(
        app,
        ["generate", "stubs", "-d", fresh_database, "--format", "dataclass", "-o", str(out)],
    )

    assert result.exit_code == 0, result.output
    assert "BaseModel" not in out.read_text()


@pytest.mark.parametrize("output_format", ["dataclass", "typeddict"])
def test_stubs_in_another_format_return_the_result(
    fresh_database: str, tmp_path: Path, load_module, output_format: str
) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(
            "CREATE FUNCTION widget_summary(p_id bigint) RETURNS jsonb LANGUAGE sql "
            "STABLE AS $$ SELECT jsonb_build_object('id', p_id, 'label', 'x') $$"
        )
    out = tmp_path / "stubs.py"

    result = runner.invoke(
        app,
        ["generate", "stubs", "-d", fresh_database, "--format", output_format, "-o", str(out)],
    )

    assert result.exit_code == 0, result.output
    stubs = load_module(out)
    with psycopg.connect(fresh_database) as conn:
        summary = stubs.widget_summary(conn, 5)
    fields = summary if output_format == "typeddict" else vars(summary)
    assert (fields["id"], fields["label"]) == (5, "x")


def test_an_unknown_stub_format_is_refused(database: str, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["generate", "stubs", "-d", database, "--format", "bogus", "-o", str(tmp_path / "s.py")],
    )

    assert result.exit_code != 0
    assert not (tmp_path / "s.py").exists()


def test_stubs_on_stdout_are_the_python_they_would_write(database: str, tmp_path: Path) -> None:
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(
            "CREATE FUNCTION tags(p text) RETURNS text[] LANGUAGE sql IMMUTABLE AS 'SELECT ARRAY[p]'"
        )
    out = tmp_path / "stubs.py"
    written = runner.invoke(app, ["generate", "stubs", "-d", database, "-o", str(out)])
    assert written.exit_code == 0, written.output

    result = runner.invoke(app, ["generate", "stubs", "-d", database], env=_NO_TERMINAL)

    assert result.exit_code == 0, result.output
    compile(result.stdout, "<stdout>", "exec")
    body = out.read_text().split("\n", 3)[3]
    assert result.stdout.rstrip("\n").endswith(body.rstrip("\n"))
