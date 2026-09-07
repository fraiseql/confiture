"""One ``--format`` validator for every command.

Fifteen commands validated ``--format`` by hand — each with its own message,
stream and exit code (1, 2, or a swallowed ``typer.Exit``) — and the rest did
not validate at all. Contract: an invalid ``--format`` on *any* command exits 5
with the error on stderr and nothing on stdout. Commands are discovered from
the Typer app so a new command cannot opt out by omission.
"""

from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

# `generate stubs --format` selects an output language (pydantic, …); it is not
# the payload-format option this test is about.
EXCLUDED = {("generate", "stubs")}


def _commands_with_format() -> list[tuple[str, ...]]:
    root = typer.main.get_command(app)
    found: list[tuple[str, ...]] = []

    def walk(cmd: object, path: tuple[str, ...]) -> None:
        subcommands = getattr(cmd, "commands", None)
        if subcommands is not None:  # a group (TyperGroup is not this module's click.Group)
            for name, sub in subcommands.items():
                walk(sub, (*path, name))
            return
        params = getattr(cmd, "params", [])
        if (
            any("--format" in (getattr(p, "opts", None) or []) for p in params)
            and path not in EXCLUDED
        ):
            found.append(path)

    walk(root, ())
    return sorted(found)


COMMANDS = _commands_with_format()


def test_discovery_sees_the_known_surface() -> None:
    assert ("migrate", "up") in COMMANDS
    assert ("migrate", "status") in COMMANDS
    assert ("build",) in COMMANDS
    assert len(COMMANDS) >= 40, COMMANDS


@pytest.mark.parametrize("path", COMMANDS, ids=" ".join)
def test_bogus_format_exits_5_on_stderr(path: tuple[str, ...]) -> None:
    result = runner.invoke(app, [*path, "--format", "bogus"])

    assert result.exit_code == 5, result.output
    assert result.stdout == "", result.stdout
    assert "Invalid --format" in result.stderr, result.stderr
    assert "bogus" in result.stderr


def test_preflight_rejects_csv() -> None:
    result = runner.invoke(app, ["migrate", "preflight", "--format", "csv"])
    assert result.exit_code == 5, result.output
    assert "csv" in result.stderr
