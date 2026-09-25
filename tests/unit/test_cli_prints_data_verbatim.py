"""Every value a console f-string interpolates is printed as data, not read as markup (#409).

Rich reads ``[...]`` in a printed string as a style tag, so ``console.print(f"… {v}")``
with a ``v`` holding ``[tree_001]``, ``int[]`` or ``db/[legacy]/x.sql`` drops the
bracketed text, restyles the line, or raises ``MarkupError``. Under ``cli/``, a value
interpolated into an f-string passed to a ``print``, ``log``, ``status``, ``rule`` or
``input`` method — every such receiver under ``cli/`` is a Rich console, whatever it
is named (``console``, ``cons``, ``out``) — with markup on, is one of:

- ``verbatim(v)`` / ``verbatim(v, spec)`` (or rich's ``escape``): data;
- ``markup(v)``: markup confiture built itself;
- in a style tag's position (``[{color}]``, ``[/{color}]``, ``[bold {color}]``);
- ``len(…)``, or a number written with a numeric format spec (``{n:,}``, ``{t:.2f}``),
  which cannot hold a bracket.

Anything else fails here, with its file and line.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from rich.console import Console

from confiture.cli.markup import markup, verbatim

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "python" / "confiture" / "cli"
METHODS = frozenset({"print", "log", "status", "rule", "input"})
SAFE_CALLS = frozenset({"verbatim", "markup", "escape", "len"})
#: A format spec whose presentation type is a number's (or a thousands separator).
NUMERIC_SPEC = re.compile(r"^[<>=^]?[+\- ]?#?0?\d*[,_]?(\.\d+)?[bcdeEfFgGnoxX%,]$")


def _console_fstrings(tree: ast.AST) -> list[ast.JoinedStr]:
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in METHODS:
            continue
        if any(keyword.arg == "markup" for keyword in node.keywords):
            continue
        found.extend(arg for arg in node.args if isinstance(arg, ast.JoinedStr))
    return found


def _unsafe(fstring: ast.JoinedStr) -> list[ast.FormattedValue]:
    unsafe = []
    literal = ""
    for part in fstring.values:
        if isinstance(part, ast.Constant):
            literal += str(part.value)
            continue
        assert isinstance(part, ast.FormattedValue)
        in_tag = literal.rfind("[") > literal.rfind("]")
        literal += "x"
        value = part.value
        if in_tag:
            continue
        if isinstance(value, ast.Call) and getattr(value.func, "id", None) in SAFE_CALLS:
            continue
        spec = part.format_spec
        if (
            spec is not None
            and all(isinstance(v, ast.Constant) for v in spec.values)
            and NUMERIC_SPEC.match("".join(str(v.value) for v in spec.values))
        ):
            continue
        unsafe.append(part)
    return unsafe


def _sites(source: str) -> list[int]:
    tree = ast.parse(source)
    return [part.lineno for js in _console_fstrings(tree) for part in _unsafe(js)]


def test_every_console_fstring_prints_its_values_as_data() -> None:
    found = [
        f"{path.relative_to(REPO).as_posix()}:{line}"
        for path in sorted(CLI.rglob("*.py"))
        for line in _sites(path.read_text(encoding="utf-8"))
    ]
    assert found == [], "values printed as markup:\n  " + "\n  ".join(found)


@pytest.mark.parametrize(
    ("source", "is_site"),
    [
        ('console.print(f"x {v}")', True),
        ('error_console.print(f"x {v!r}")', True),
        ('cons.print(f"x {v}")', True),
        ('console.status(f"x {v}")', True),
        ('console.print(f"a", f"b {v}")', True),
        ('console.print(f"x {v:<9}")', True),
        ('console.print(f"x {verbatim(v)}")', False),
        ('console.print(f"x {markup(v)}")', False),
        ('console.print(f"[{color}]x[/{color}]")', False),
        ('console.print(f"[bold {color}]x[/]")', False),
        ('console.print(f"{len(v)} files")', False),
        ('console.print(f"{n:,} rows in {t:.2f}s")', False),
        ('console.print(f"x {v}", markup=False)', False),
        ('logger.info(f"x {v}")', False),
    ],
)
def test_the_guard_reads_code(source: str, *, is_site: bool) -> None:
    assert bool(_sites(source)) is is_site


def test_verbatim_prints_every_bracket() -> None:
    console = Console(record=True, width=200, color_system=None)
    console.print(f"[red]{verbatim('[tree_001] int[] db/[legacy]/x.sql')}[/red]")
    assert console.export_text().strip() == "[tree_001] int[] db/[legacy]/x.sql"


def test_markup_is_rendered() -> None:
    console = Console(record=True, width=200, color_system=None)
    console.print(f"{markup('[green]ok[/green]')} {verbatim(3.5, '.1f')}")
    assert console.export_text().strip() == "ok 3.5"
