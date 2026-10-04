"""confiture prints through its ``Printer``, and a value printed is data (#600).

The printer takes templates, literals and Rich renderables; ty refuses a computed
``str`` (``invalid-argument-type`` is on for the modules that print). What ty
cannot see is a way around the printer, so this fails, in the modules converted
to it — every module under ``python/`` but :data:`NOT_PRINTERS` — on:

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

#: Modules that print and cannot hold a ``Printer``, and why.
NOT_PRINTERS: dict[str, str] = {
    "core/error_handler.py": (
        "core does not import cli (test_import_graph.py): it prints through the Rich "
        "console its caller hands it (printer.rich), each value through rich's escape"
    ),
    "core/seed/applier.py": (
        "core does not import cli (test_import_graph.py): the seed command hands it "
        "printer.rich, and it prints each value through rich's escape"
    ),
}

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


def _modules() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--", "python/confiture/*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO_ROOT / line for line in out.splitlines() if line]


def _key(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


def test_every_module_prints_through_the_printer() -> None:
    refused = [
        f"{_key(path)}:{line}: {what}"
        for path in _modules()
        if _key(path) != "cli/markup.py" and _key(path) not in NOT_PRINTERS
        for line, what in findings(path.read_text())
    ]
    assert refused == []


def test_every_exempt_module_still_prints() -> None:
    """An exemption whose module no longer prints is a reason with nothing to explain."""
    printing = {_key(p) for p in _modules() if list(findings(p.read_text()))}
    assert sorted(set(NOT_PRINTERS) - printing) == []


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
