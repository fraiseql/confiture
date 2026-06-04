"""Reachability guard: every registered CLI command is invocable.

Complements ``test_library_api_exposure`` (which proves every ``_LAZY_IMPORTS``
symbol resolves) on the CLI side. It walks the live Typer ``app`` — the exact
tree the ``confiture`` console script exposes — and asserts that **every**
command, at every nesting depth, answers ``--help`` with exit 0.

A ``--help`` that exits 0 proves the command is registered *and* its callback
module imports cleanly: a command that was added but never wired in, or whose
module raises on import, fails here. This is the no-"shipped-but-unreachable"
backstop — a new orphan command can't slip in without a test noticing.
"""

from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _walk(t: typer.Typer, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Every command path under a Typer app, recursing into subgroups."""
    paths: list[tuple[str, ...]] = []
    for cmd in t.registered_commands:
        name = cmd.name or (cmd.callback.__name__.replace("_", "-") if cmd.callback else "?")
        paths.append((*prefix, name))
    for grp in t.registered_groups:
        if grp.typer_instance is not None:
            paths.extend(_walk(grp.typer_instance, (*prefix, grp.name or "?")))
    return paths


ALL_COMMAND_PATHS = sorted(_walk(app))
ALL_GROUP_NAMES = sorted(g.name for g in app.registered_groups if g.name)

# Floor below the live count (70) so adding commands never breaks this, but
# dropping a whole group (the failure we care about) does.
_MIN_COMMANDS = 60


def test_command_tree_is_non_trivial() -> None:
    """The walk finds the full command surface, not an empty/half-registered app."""
    assert len(ALL_COMMAND_PATHS) >= _MIN_COMMANDS, ALL_COMMAND_PATHS
    # The major subcommand groups must all still be mounted.
    for group in ("migrate", "seed", "branch", "coordinate", "generate"):
        assert group in ALL_GROUP_NAMES, f"group {group!r} not registered"


def test_schema_to_schema_group_is_reachable() -> None:
    """The Phase-04-wired Medium-4 group is present with all six subcommands."""
    s2s = {p[2] for p in ALL_COMMAND_PATHS if p[:2] == ("migrate", "schema-to-schema")}
    assert s2s == {"setup", "analyze", "migrate", "migrate-table", "verify", "cleanup"}, s2s


@pytest.mark.parametrize("path", ALL_COMMAND_PATHS, ids=lambda p: " ".join(p))
def test_command_help_is_reachable(path: tuple[str, ...]) -> None:
    """`<command> --help` exits 0 — the command is registered and imports cleanly."""
    result = runner.invoke(app, [*path, "--help"])
    assert result.exit_code == 0, f"`{' '.join(path)} --help` failed:\n{result.output}"
