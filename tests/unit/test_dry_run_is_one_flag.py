""" "Do not act" has one spelling, and a command that previews by default says so.

There were six ways to ask for a preview: ``--dry-run``, ``--dry-run-execute``,
``--apply`` (acting, on two commands that preview by default), ``--no-dry-run``,
``bootstrap``'s ``--check/--no-check`` and its three-way ``--check/--dry-run/--apply``.
A command either acts by default and takes ``--dry-run`` to preview, or previews
by default and takes ``--mode`` whose default only looks (``check``, ``plan``) —
never both, and never one of the retired spellings (owner decisions 3 and 10).

``--dry-run-execute`` on ``migrate up`` is not a spelling of either: it executes
every pending migration inside a SAVEPOINT and rolls back. It keeps its name.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from typer.main import get_command

from confiture.cli.main import app
from confiture.cli.options import PREVIEW_MODES

RETIRED = {"--apply", "--no-dry-run"}
CLI_ROOT = Path(__file__).resolve().parents[2] / "python" / "confiture" / "cli"


def _leaves(command: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[str, Any]]:
    subcommands = getattr(command, "commands", None)
    if not subcommands:
        yield " ".join(path), command
        return
    for name, sub in sorted(subcommands.items()):
        yield from _leaves(sub, (*path, name))


def _options(command: Any) -> dict[str, Any]:
    return {s: p for p in command.params for s in (*p.opts, *getattr(p, "secondary_opts", ()))}


LEAVES = dict(_leaves(get_command(app)))


def test_no_command_takes_a_retired_spelling() -> None:
    found = {
        path: sorted(RETIRED & set(_options(command)))
        for path, command in LEAVES.items()
        if RETIRED & set(_options(command))
    }
    assert found == {}


def test_no_command_takes_a_boolean_check_mode() -> None:
    """``lint-unified --check`` selects checks; a *boolean* ``--check`` is a mode."""
    found = [
        path
        for path, command in LEAVES.items()
        if (option := _options(command).get("--check")) is not None and option.is_flag
    ]
    assert found == []


def test_a_command_previews_by_dry_run_or_by_mode_never_both() -> None:
    both = [
        path
        for path, command in LEAVES.items()
        if {"--dry-run", "--mode"} <= set(_options(command))
    ]
    assert both == []


def test_every_mode_defaults_to_looking() -> None:
    acting = {
        path: option.default
        for path, command in LEAVES.items()
        if (option := _options(command).get("--mode")) is not None
        and option.default not in PREVIEW_MODES
    }
    assert acting == {}


def test_every_mode_comes_from_mode_option() -> None:
    declared = [
        f"{path.relative_to(CLI_ROOT).as_posix()}:{node.lineno}"
        for path in sorted(CLI_ROOT.rglob("*.py"))
        if path.name != "options.py"
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Constant) and node.value == "--mode"
    ]
    assert declared == []
