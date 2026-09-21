"""Every exit a command takes is named.

An exit integer is a contract two adapters branch on (fraisier's and
fraisier-core's), so a command that writes ``typer.Exit(2)`` states a meaning
nobody can read off the line: is that "no ledger", "a usage error", or a
config path that does not exist — which every other command calls exit 5?
Named, it is one of three outcomes that are not errors
(``error_codes.SUCCESS``, ``FINDINGS``, ``USAGE``) or the registered code of
the error it is (``error_codes.exit_code_of("PRECON_1001")``), and the registry
decides the integer. Any exit spelled as an integer literal under ``cli/`` —
``typer.Exit(2)``, ``typer.Exit(code=2)``, ``SystemExit(2)``, ``sys.exit(2)`` —
fails here. The guard reads code: a docstring that quotes ``typer.Exit(1)`` is
not a site.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from confiture.error_codes import CANONICAL_EXIT_CODES

CLI_ROOT = Path(__file__).resolve().parents[2] / "python" / "confiture" / "cli"
EXIT_CALLS = {"Exit", "SystemExit", "exit"}


def _literal_exit(node: ast.Call) -> bool:
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name not in EXIT_CALLS:
        return False
    values = [*node.args[:1], *(kw.value for kw in node.keywords if kw.arg == "code")]
    return any(
        isinstance(v, ast.Constant) and isinstance(v.value, int) and not isinstance(v.value, bool)
        for v in values
    )


def _calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def test_no_exit_is_an_integer_literal() -> None:
    found = [
        f"{path.relative_to(CLI_ROOT).as_posix()}:{call.lineno}"
        for path in sorted(CLI_ROOT.rglob("*.py"))
        for call in _calls(path)
        if _literal_exit(call)
    ]
    assert found == [], "exits spelled as integers:\n  " + "\n  ".join(found)


def test_every_named_error_exit_is_a_registered_code() -> None:
    """``exit_code_of("X")`` with an X the registry does not know fails at run time."""
    unknown = [
        f"{path.relative_to(CLI_ROOT).as_posix()}:{call.lineno} {call.args[0].value!r}"
        for path in sorted(CLI_ROOT.rglob("*.py"))
        for call in _calls(path)
        if getattr(call.func, "id", getattr(call.func, "attr", None)) == "exit_code_of"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value not in CANONICAL_EXIT_CODES
    ]
    assert unknown == []


@pytest.mark.parametrize(
    ("source", "is_site"),
    [
        ("typer.Exit(2)", True),
        ("typer.Exit(code=2)", True),
        ("raise SystemExit(1)", True),
        ("sys.exit(0)", True),
        ("typer.Exit(FINDINGS)", False),
        ("typer.Exit(error.exit_code)", False),
        ('"""typer.Exit(1)"""', False),
    ],
)
def test_the_guard_sees_the_spellings(source: str, is_site: bool) -> None:
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)]
    assert any(_literal_exit(c) for c in calls) is is_site
