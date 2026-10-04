"""SQL confiture executes is a template string: one way to compose it (#599).

psycopg 3.3 renders a ``t"…"``: ``{name:i}`` is quoted as an identifier,
``{value:l}`` written as a literal, ``{fragment:q}`` nested, and a bare
``{value}`` bound as a parameter. The statement reads as itself, and putting raw
text into it takes an explicit ``Template(text)`` interpolated with ``:q``.
``psycopg.sql``'s builders (``SQL``, ``Identifier``, ``Literal``, ``Placeholder``,
``Composed``) said the same thing at a distance, and an f-string, ``%``,
``.format()`` or ``+`` handed to ``execute`` said it unsafely.

``sql.SQL(", ").join(…)`` is psycopg's join of templates, not composition, and is
not matched. Generated DDL — text written to a file, never executed here — stays
on ``schema_identity.quote_identifier`` (``test_one_identifier_quoter.py``).

The guard covers :data:`CONVERTED`, the modules whose executed SQL is templates;
the conversion widens it until it covers ``python/``.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "python" / "confiture"

#: The modules whose executed SQL is templates, relative to ``python/confiture``.
CONVERTED: tuple[str, ...] = (
    "core/backfill.py",
    "core/dry_run.py",
    "core/large_tables.py",
    "core/locking.py",
    "core/schema_to_schema.py",
    "core/seed/executor.py",
    "core/seed/validation/prep_seed/level_4_runtime.py",
    "core/seed/validation/prep_seed/level_5_execution.py",
    "core/seed/validation/prep_seed/resolvers.py",
    "core/step_runner.py",
    "core/syncer.py",
    "testing/fixtures/data_validator.py",
    "testing/fixtures/migration_runner.py",
    "testing/sandbox.py",
)

#: A call this guard would refuse, kept for a reason: ``(module, line text)`` → why.
ALLOWED: dict[tuple[str, str], str] = {}

BUILDERS = frozenset({"SQL", "Identifier", "Literal", "Placeholder", "Composed"})
EXECUTORS = frozenset({"execute", "executemany", "copy"})


def _is_join(node: ast.Call) -> bool:
    """``sql.SQL("<constant>").join(…)``: psycopg's join, the receiver of ``.join``."""
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "SQL"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
    )


def _joined(tree: ast.AST) -> set[int]:
    return {
        id(node.func.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and isinstance(node.func.value, ast.Call)
        and _is_join(node.func.value)
    }


def _composed_by_hand(statement: ast.expr) -> bool:
    if isinstance(statement, ast.JoinedStr):
        return True
    if isinstance(statement, ast.BinOp) and isinstance(statement.op, (ast.Mod, ast.Add)):
        return True
    return (
        isinstance(statement, ast.Call)
        and isinstance(statement.func, ast.Attribute)
        and statement.func.attr == "format"
        and isinstance(statement.func.value, ast.Constant)
    )


def _sql_modules(tree: ast.AST) -> tuple[set[str], set[str]]:
    """The names *tree* binds to ``psycopg.sql``, and to its builders."""
    modules, builders = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "psycopg":
            modules |= {a.asname or a.name for a in node.names if a.name == "sql"}
        if isinstance(node, ast.ImportFrom) and node.module == "psycopg.sql":
            builders |= {a.asname or a.name for a in node.names if a.name in BUILDERS}
    return modules, builders


def _builder(node: ast.Call, modules: set[str], builders: set[str]) -> str | None:
    func = node.func
    if isinstance(func, ast.Name) and func.id in builders:
        return func.id
    if not isinstance(func, ast.Attribute) or func.attr not in BUILDERS:
        return None
    receiver = func.value
    if isinstance(receiver, ast.Name) and receiver.id in modules:
        return f"{receiver.id}.{func.attr}"
    if isinstance(receiver, ast.Attribute) and ast.unparse(receiver) == "psycopg.sql":
        return f"psycopg.sql.{func.attr}"
    return None


def findings(source: str) -> Iterator[tuple[int, str]]:
    """``(line, what)`` for every composition *source* does outside templates."""
    tree = ast.parse(source)
    joins = _joined(tree)
    modules, builders = _sql_modules(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        builder = _builder(node, modules | {"sql", "pgsql"}, builders)
        if builder is not None and id(node) not in joins:
            yield node.lineno, f"{builder}(…)"
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in EXECUTORS
            and node.args
            and _composed_by_hand(node.args[0])
        ):
            yield node.lineno, f".{node.func.attr}() of a string composed by hand"


@pytest.mark.parametrize(
    ("source", "count"),
    [
        ('cur.execute(t"SELECT {a:i}")', 0),
        ('cur.execute(sql.SQL("SELECT {}").format(sql.Identifier(a)))', 2),
        ('cur.execute(f"SAVEPOINT {name}")', 1),
        ('cur.execute("SELECT %s" % v)', 1),
        ('cur.execute("SELECT " + v)', 1),
        ('cur.execute("SELECT {}".format(v))', 1),
        ('cur.execute("SELECT 1 WHERE x = %s", (v,))', 0),
        ('cur.execute(t"SELECT {sql.SQL(", ").join(parts):q}")', 0),
        ('cur.execute(t"SELECT 1 WHERE {Template(where):q}")', 0),
        ("pgsql.Literal(v)", 1),
        ("import psycopg.sql\npsycopg.sql.Identifier(a)", 1),
        ("from psycopg.sql import SQL, Identifier\nSQL('x {}').format(Identifier(a))", 2),
    ],
)
def test_the_rows(source: str, count: int) -> None:
    assert len(list(findings(source))) == count


def _refused() -> list[tuple[str, str]]:
    refused = []
    for module in CONVERTED:
        path = PACKAGE / module
        lines = path.read_text().splitlines()
        for line, what in findings(path.read_text()):
            key = (module, lines[line - 1].strip())
            if key not in ALLOWED:
                refused.append((f"{module}:{line}", what))
    return refused


def test_executed_sql_is_composed_as_templates() -> None:
    assert _refused() == [], (
        "compose executed SQL as a t-string: {name:i}, {value:l}, {fragment:q}, "
        "or a bare {value} for a parameter"
    )


def test_every_allowed_call_still_exists() -> None:
    present = set()
    for module in CONVERTED:
        path = PACKAGE / module
        lines = path.read_text().splitlines()
        present |= {(module, lines[line - 1].strip()) for line, _ in findings(path.read_text())}
    assert sorted(set(ALLOWED) - present) == []


def test_every_converted_module_exists() -> None:
    assert [m for m in CONVERTED if not (PACKAGE / m).is_file()] == []
