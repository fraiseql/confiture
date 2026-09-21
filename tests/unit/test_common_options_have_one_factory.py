"""The six options most commands take are declared once each.

``--config`` was declared 39 times in four spellings (``-c`` or not, first or
second) with three defaults; ``--output`` 20 times, twice without its ``-o``.
A flag that is spelled per command drifts per command. Each of the six is now a
factory in ``cli/options.py``, and a ``typer.Option`` naming one of their flags
anywhere else fails here. A factory takes the command's default where the
default is a different lookup (owner decision 8): what it fixes is the flag,
its short form and its help.
"""

from __future__ import annotations

import ast
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parents[2] / "python" / "confiture" / "cli"
FACTORIES = CLI_ROOT / "options.py"
FLAGS = {"--config", "--env", "--database-url", "--migrations-dir", "--output", "--verbose"}

#: Modules that keep their own declarations, and why.
EXEMPT: dict[str, str] = {}


def _is_option(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)) == "Option"


def _implicit_flags(tree: ast.AST) -> dict[int, str]:
    """``database_url: str = typer.Option(None)``: Typer names the flag after the parameter."""
    found: dict[int, str] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        args = fn.args
        positional = [*args.posonlyargs, *args.args]
        defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
        for arg, default in [
            *zip(positional, defaults, strict=True),
            *zip(args.kwonlyargs, args.kw_defaults, strict=True),
        ]:
            flag = "--" + arg.arg.replace("_", "-")
            decls = [
                a
                for a in getattr(default, "args", [])
                if isinstance(a, ast.Constant)
                and isinstance(a.value, str)
                and a.value.startswith("-")
            ]
            if flag in FLAGS and default is not None and _is_option(default) and not decls:
                found[default.lineno] = flag
    return found


def _declared_flags(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    rel = path.relative_to(CLI_ROOT).as_posix()
    found = [
        f"{rel}:{line} {flag} (named by its parameter)"
        for line, flag in _implicit_flags(tree).items()
    ]
    for node in ast.walk(tree):
        if _is_option(node):
            found.extend(
                f"{rel}:{node.lineno} {arg.value}"
                for arg in node.args
                if isinstance(arg, ast.Constant) and arg.value in FLAGS
            )
    return found


def test_the_common_flags_are_declared_only_by_their_factories() -> None:
    found = [
        hit
        for path in sorted(CLI_ROOT.rglob("*.py"))
        if path != FACTORIES and path.relative_to(CLI_ROOT).as_posix() not in EXEMPT
        for hit in _declared_flags(path)
    ]
    assert found == [], "common flags declared outside cli/options.py:\n  " + "\n  ".join(found)


def test_every_factory_flag_is_spelled_in_the_factories() -> None:
    tree = ast.parse(FACTORIES.read_text())
    spelled = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value in FLAGS}
    assert spelled == FLAGS


def test_the_guard_sees_a_flag_named_by_its_parameter() -> None:
    tree = ast.parse("def f(database_url: str = typer.Option(None), x: int = typer.Option(1)): ...")
    assert list(_implicit_flags(tree).values()) == ["--database-url"]


def test_every_exemption_still_declares_a_common_flag() -> None:
    for module in EXEMPT:
        assert _declared_flags(CLI_ROOT / module), (
            f"{module} is exempt but declares none: delete it"
        )


def test_no_command_gives_one_option_string_two_meanings() -> None:
    """Click keeps the last of two options that share a string; the first goes silent.

    ``debug cte`` gave ``-f`` to ``--file`` and to ``--format``, so ``-f q.sql``
    was read as a format and refused.
    """
    from collections import Counter

    from typer.main import get_command

    from confiture.cli.main import app

    def leaves(command, path=()):
        subcommands = getattr(command, "commands", None)
        if not subcommands:
            yield " ".join(path), command
            return
        for name, sub in subcommands.items():
            yield from leaves(sub, (*path, name))

    repeated = {}
    for path, command in leaves(get_command(app)):
        strings = Counter(
            s for p in command.params for s in (*p.opts, *getattr(p, "secondary_opts", ()))
        )
        if twice := sorted(s for s, n in strings.items() if n > 1):
            repeated[path] = twice
    assert repeated == {}
