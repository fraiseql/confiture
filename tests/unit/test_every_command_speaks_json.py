"""Every command can answer in JSON, or says why it cannot.

The envelope is only a contract if every command has one: a script driving
confiture should not have to learn which commands scrape and which parse. A
leaf of the live command tree speaks JSON when it takes ``--json`` or a
``--format`` that offers ``json`` (``format_option`` names its values in the
help it writes). The commands that cannot are listed, each with the reason.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from typer.main import get_command

from confiture.cli.main import app

#: A leaf that has no JSON, and why.
SILENT = {
    "init": "interactive: it asks, then scaffolds a project",
    "mcp": "long-running: it serves the MCP protocol on stdio",
    "restore": "long-running: it streams pg_restore's own progress",
    "seed convert": "its stdout is the COPY SQL it converts, not a report on it",
    "generate pgtap": "its stdout is the pgTAP SQL it generates",
    "generate stubs": "its stdout is the Python it generates; --format names that code's style",
    "hooks test": "its stdout is the notification it renders, through StdoutTransport",
}


def _leaves(command: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[str, Any]]:
    subcommands = getattr(command, "commands", None)
    if not subcommands:
        yield " ".join(path), command
        return
    for name, sub in sorted(subcommands.items()):
        yield from _leaves(sub, (*path, name))


def _speaks_json(command: Any) -> bool:
    for param in command.params:
        opts = set(getattr(param, "opts", ()))
        if "--json" in opts:
            return True
        if "--format" in opts and "json" in (getattr(param, "help", None) or ""):
            return True
    return False


LEAVES = dict(_leaves(get_command(app)))


def test_every_command_speaks_json_or_says_why_not() -> None:
    mute = sorted(
        path for path, command in LEAVES.items() if not _speaks_json(command) and path not in SILENT
    )
    assert mute == [], "commands with no JSON and no stated reason:\n  " + "\n  ".join(mute)


@pytest.mark.parametrize("path", sorted(SILENT))
def test_every_silence_is_still_a_silent_command(path: str) -> None:
    assert path in LEAVES, f"{path!r} is no longer a command: delete its entry"
    assert not _speaks_json(LEAVES[path]), f"{path!r} speaks JSON now: delete its entry"
