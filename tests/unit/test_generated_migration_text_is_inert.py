"""A name in the schema never becomes code in a generated migration.

A quoted identifier may hold any character but NUL: a double quote, a
backslash, a newline. ``migrate generate`` writes names into a Python string
literal (``self.execute(...)``), into ``#`` comments and into ``--`` comments;
each must stay what it is, whatever the name holds. Checked by parsing what
was written: the Python with :mod:`ast`, the SQL with pglast.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pglast
import pytest

from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.migration_generator import MigrationGenerator
from confiture.platform import diff

#: Generated DDL is tested with names the differ refuses (DIFFER_403): the second layer.
pytestmark = pytest.mark.usefixtures("quoted_names_allowed")

#: A column name that closes a triple-quoted string (`quote_identifier` wraps it in `"`).
_CLOSES_THE_STRING = "\");__import__('os').system('x');self.execute(\""
#: A name that ends a comment line and starts a statement.
_ENDS_THE_LINE = "e\nDROP TABLE victim;--"
_ENDS_THE_PY_LINE = "e\n__import__('os').system('x')\n#"


def _calls(source: str) -> list[str]:
    """Every call in *source*, by its callee's text."""
    return [
        ast.unparse(node.func) for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
    ]


def _executed(source: str) -> list[str]:
    """The string each ``self.execute`` receives."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "self.execute":
            (arg,) = node.args
            assert isinstance(arg, ast.Constant)
            found.append(arg.value)
    return found


def _python_migration(tmp_path: Path, old: str, new: str) -> str:
    path = MigrationGenerator(migrations_dir=tmp_path).generate(diff(old, new), "m")
    return path.read_text()


def test_a_name_that_closes_the_string_stays_inside_it(tmp_path: Path) -> None:
    old = "CREATE TABLE t (a int);"
    new = f'CREATE TABLE t (a int, "{_CLOSES_THE_STRING.replace(chr(34), chr(34) * 2)}" int);'

    source = _python_migration(tmp_path, old, new)

    assert set(_calls(source)) == {"self.execute"}
    generated = [DifferSQLGenerator().generate_up(c) for c in diff(old, new).changes]
    assert _executed(source)[: len(generated)] == [sql.rstrip("\n") for sql in generated if sql]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'a\\nb'",
        'SELECT "x"',
        'SELECT 1 AS "a"""',
        "SELECT E'\\\\'\nFROM t",
        "SELECT '\r'",
    ],
)
def test_any_statement_is_written_as_a_literal_of_itself(sql: str) -> None:
    from confiture.core.migration_generator import _execute_call

    (call,) = ast.parse(_execute_call(sql).strip()).body
    assert isinstance(call, ast.Expr)
    assert _executed(ast.unparse(call)) == [sql]


def test_a_name_with_a_newline_stays_in_its_python_comment(tmp_path: Path) -> None:
    """An added enum label cannot be taken back: ``down()`` says so in a comment."""
    name = _ENDS_THE_PY_LINE.replace('"', '""')
    old = f"CREATE TYPE \"{name}\" AS ENUM ('a');"
    new = f"CREATE TYPE \"{name}\" AS ENUM ('a', 'b');"

    source = _python_migration(tmp_path, old, new)

    assert set(_calls(source)) <= {"self.execute"}


def _down_statements(tmp_path: Path, old: str, new: str) -> list[str]:
    up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(diff(old, new), "m")
    down = up.with_name(up.name.replace(".up.sql", ".down.sql"))
    return [type(raw.stmt).__name__ for raw in pglast.parse_sql(down.read_text())]


def test_a_name_with_a_newline_stays_in_its_sql_comment(tmp_path: Path) -> None:
    """The enum label's down is the ``-- confiture:irreversible`` line."""
    name = _ENDS_THE_LINE.replace('"', '""')
    old = f"CREATE TYPE \"{name}\" AS ENUM ('a');"
    new = f"CREATE TYPE \"{name}\" AS ENUM ('a', 'b');"

    assert _down_statements(tmp_path, old, new) == []


def test_a_warning_naming_a_table_with_a_newline_stays_a_comment() -> None:
    """An unnamed index cannot be generated, and the warning names its table."""
    table = _ENDS_THE_LINE.replace('"', '""')
    old = f'CREATE TABLE "{table}" (a int);'
    new = f'CREATE TABLE "{table}" (a int);\nCREATE INDEX ON "{table}" (a);'

    written = "".join(DifferSQLGenerator().generate_up(c) or "" for c in diff(old, new).changes)

    assert [type(raw.stmt).__name__ for raw in pglast.parse_sql(written)] == []
