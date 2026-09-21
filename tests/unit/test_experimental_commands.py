"""Which commands are experimental, and that each one says so where a reader looks.

An experimental command is shipped, documented and run against a database by the
integration suite (``tests/integration/test_experimental_commands.py``). What it does
not make is a promise about its interface: its options and its output may change in
any release, without a deprecation. So the status is stated in the first words of
its ``--help`` — which ``docs/reference/cli.md`` reprints — and nowhere else, so that
the word marks a list and not a mood.
"""

from __future__ import annotations

from typer.main import get_command

from confiture.cli.main import app

#: The experimental command groups, and why each is not yet a contract.
EXPERIMENTAL = {
    "debug": "one subcommand, no caller, and a payload shaped by its first use",
    "mcp": "tracks the Model Context Protocol, which is itself still moving",
}

PREFIX = "Experimental:"


def _groups() -> dict[str, str]:
    root = get_command(app)
    return {name: command.help or "" for name, command in root.commands.items()}


def test_every_experimental_command_says_so_first() -> None:
    groups = _groups()
    silent = sorted(name for name in EXPERIMENTAL if not groups[name].startswith(PREFIX))
    assert silent == [], f"experimental commands whose --help does not begin {PREFIX!r}: {silent}"


def test_no_other_command_calls_itself_experimental() -> None:
    claimed = sorted(
        name for name, text in _groups().items() if PREFIX in text and name not in EXPERIMENTAL
    )
    assert claimed == [], f"add these to EXPERIMENTAL with a reason, or drop the word: {claimed}"
