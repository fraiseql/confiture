"""confiture prints through its ``Printer``, and a value printed is data (#600).

The printer takes templates, literals and Rich renderables; ty refuses a computed
``str`` (``invalid-argument-type`` is on for the modules that print). What ty
cannot see is a way around the printer, so this fails, in the modules converted
to it (:data:`CONVERTED`, widened until it covers ``python/``), on:

- a Rich ``Console`` or ``Table`` constructed outside ``cli/markup.py``;
- the printer's ``.rich`` console printed through (it is only handed to a Rich
  object that draws: ``Progress(console=out.rich)``);
- an f-string handed to a printing method: a template says which parts are data;
- ``verbatim(`` inside a template's interpolation (escaped twice), or anywhere
  but ``cli/markup.py``.
"""

import ast
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "python" / "confiture"
TYPING_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "printer_typing" / "printing.py"

#: The modules that print through a ``Printer``, relative to ``python/confiture``.
CONVERTED: tuple[str, ...] = ()

#: A construction or call this guard would refuse, kept for a reason.
ALLOWED: dict[tuple[str, str], str] = {}

PRINTING = frozenset({"print", "log", "rule", "status", "input", "add_row"})
RICH_CLASSES = {"rich.console": "Console", "rich.table": "Table"}


def _rich_names(tree: ast.AST) -> set[str]:
    """The names *tree* binds to Rich's ``Console`` and ``Table`` classes."""
    return {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module in RICH_CLASSES
        for alias in node.names
        if alias.name == RICH_CLASSES[node.module]
    }


def _is_rich(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "rich"


def findings(source: str) -> Iterator[tuple[int, str]]:
    tree = ast.parse(source)
    rich = _rich_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Interpolation):
            for inner in ast.walk(node.value):
                if isinstance(inner, ast.Call) and getattr(inner.func, "id", None) == "verbatim":
                    yield node.lineno, "verbatim() in a template: escaped twice"
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "verbatim":
            yield node.lineno, "verbatim() outside cli/markup.py: print a template"
        if isinstance(func, ast.Name) and func.id in rich:
            yield node.lineno, f"a Rich {func.id} built here: use cli/markup.py's"
        if not isinstance(func, ast.Attribute):
            continue
        if _is_rich(func.value) and func.attr in PRINTING | {"__call__"}:
            yield node.lineno, ".rich printed through: it is for Rich objects that draw"
        if func.attr in PRINTING and any(isinstance(a, ast.JoinedStr) for a in node.args):
            yield node.lineno, 'an f-string printed: write it t"…"'


@pytest.mark.parametrize(
    ("source", "count"),
    [
        ("from rich.console import Console\nc = Console()", 1),
        ("from rich.console import Console as _C\nc = _C(stderr=True)", 1),
        ("from rich.table import Table\nt = Table('a')", 1),
        ("from confiture.cli.markup import Table\nt = Table('a')", 0),
        ('out.print(f"x {v}")', 1),
        ('out.print(t"x {v}")', 0),
        ('out.print(t"x {verbatim(v)}")', 2),
        ("Progress(console=out.rich)", 0),
        ("out.rich.print(x)", 1),
        ('table.add_row(f"{v}")', 1),
        ("verbatim(v)", 1),
    ],
)
def test_the_rows(source: str, count: int) -> None:
    assert len(list(findings(source))) == count


def _refused() -> list[str]:
    refused = []
    for module in CONVERTED:
        path = PACKAGE / module
        lines = path.read_text().splitlines()
        for line, what in findings(path.read_text()):
            if (module, lines[line - 1].strip()) not in ALLOWED:
                refused.append(f"{module}:{line}: {what}")
    return refused


def test_the_converted_modules_print_through_the_printer() -> None:
    assert _refused() == []


def test_every_converted_module_exists() -> None:
    assert [m for m in CONVERTED if not (PACKAGE / m).is_file()] == []


def test_ty_refuses_a_computed_string_and_nothing_else() -> None:
    """The static half: a ``str`` handed to ``Printer.print`` is a type error."""
    ty = shutil.which("ty", path=str(Path(sys.executable).parent))
    assert ty is not None, "ty is a dev dependency"
    result = subprocess.run(
        [
            ty,
            "check",
            str(TYPING_FIXTURE),
            "--error",
            "invalid-argument-type",
            "--output-format",
            "concise",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    errors = [line for line in result.stdout.splitlines() if "error[" in line]
    assert len(errors) == 1 and ":13:" in errors[0], result.stdout
