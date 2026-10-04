"""A template string confiture executes means what it says to psycopg (#599).

psycopg 3.3 renders a ``t"…"`` by its interpolations: ``{name:i}`` is quoted as
an identifier, ``{value:l}`` written as a literal, ``{fragment:q}`` nested, and a
bare ``{value}`` sent as a server-side parameter (``$1``). Two things therefore
read right and fail at run time:

- a bare interpolation in a **utility statement** (``SET``, ``CREATE DATABASE``,
  ``SAVEPOINT``, ``LOCK``, ``COMMENT ON`` …): PostgreSQL takes parameters only in
  the statements its planner prepares, so the value must be ``:l``;
- ``%%`` in a template's text: a template is never ``%``-formatted, so the server
  receives both characters.

Every template passed to ``execute`` under ``python/`` is read with each
interpolation stood in by what psycopg sends, and parsed: the parser, not a
keyword list, says what kind of statement it is. ``copy()`` is not read: psycopg
merges its template client-side, so a bare value there is written in, not bound.
"""

import ast
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pglast
import pytest

from confiture.core.sql_lexer import parse_file

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The statements PostgreSQL prepares, and so the only ones a bare
#: interpolation (a ``$n`` parameter) may appear in.
PARAMETERISED = frozenset(
    {"SelectStmt", "InsertStmt", "UpdateStmt", "DeleteStmt", "MergeStmt", "CallStmt"}
)

#: What each conversion is sent as, for the parser's eyes.
STAND_IN = {"i": "x", "l": "'x'", "q": "NULL", None: "$1"}

#: The calls that send a template's bare interpolations as server-side parameters.
EXECUTORS = frozenset({"execute"})


def _stood_in(template: ast.TemplateStr) -> str:
    parts = []
    for value in template.values:
        if isinstance(value, ast.Constant):
            parts.append(str(value.value))
        elif isinstance(value, ast.Interpolation):
            spec = value.format_spec
            conversion = (
                "".join(str(v.value) for v in spec.values if isinstance(v, ast.Constant))
                if isinstance(spec, ast.JoinedStr)
                else None
            )
            parts.append(STAND_IN.get(conversion or None, "$1"))
    return "".join(parts)


def _has_bare(template: ast.TemplateStr) -> bool:
    return any(
        isinstance(value, ast.Interpolation) and value.format_spec is None
        for value in template.values
    )


def _executed(tree: ast.AST) -> Iterator[ast.TemplateStr]:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in EXECUTORS
            and node.args
            and isinstance(node.args[0], ast.TemplateStr)
        ):
            yield node.args[0]


def findings(source: str) -> list[str]:
    """What is wrong with the templates *source* executes, one line each."""
    tree = ast.parse(source)
    found = [
        f"line {node.lineno}: %% is sent as written"
        for node in ast.walk(tree)
        if isinstance(node, ast.TemplateStr)
        and any(isinstance(v, ast.Constant) and "%%" in str(v.value) for v in node.values)
    ]
    for template in _executed(tree):
        if not _has_bare(template):
            continue
        text = _stood_in(template)
        try:
            statements = parse_file(text).statements
        except pglast.parser.ParseError as error:
            found.append(f"line {template.lineno}: unreadable as SQL ({error}): {text}")
            continue
        kinds = {type(raw.stmt).__name__ for raw in statements}
        if kinds - PARAMETERISED:
            found.append(
                f"line {template.lineno}: a bare interpolation in {sorted(kinds)} is a "
                f"parameter PostgreSQL refuses there; write it {{…:l}}: {text}"
            )
    return found


@pytest.mark.parametrize(
    ("source", "flagged"),
    [
        ('cur.execute(t"SET statement_timeout = {ms}")', True),
        ('cur.execute(t"SET statement_timeout = {ms:l}")', False),
        ('cur.execute(t"SELECT {a} ")', False),
        ("cur.execute(t\"SELECT 1 WHERE n LIKE 'pg_%%'\")", True),
        ('cur.execute(t"CREATE DATABASE {db:i} TEMPLATE {tpl:i}")', False),
        ('cur.execute(t"SAVEPOINT {name:i}")', False),
        ('cur.execute(t"DELETE FROM {table:i} WHERE lock_id = {lock_id}")', False),
        ('cur.copy(t"COPY {table:i} FROM STDIN (FORMAT {fmt})")', False),
        ('cur.execute(t"SELECT {cols:q} FROM {table:i} WHERE id = {v}")', False),
    ],
)
def test_the_rows(source: str, flagged: bool) -> None:
    assert bool(findings(source)) is flagged, findings(source)


def _tracked() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--", "python/*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO_ROOT / line for line in out.splitlines() if line]


def test_every_executed_template_means_what_it_says() -> None:
    wrong = [
        f"{path.relative_to(REPO_ROOT)} {finding}"
        for path in _tracked()
        for finding in findings(path.read_text())
    ]
    assert wrong == []
