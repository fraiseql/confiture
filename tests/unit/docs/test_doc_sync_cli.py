"""Executable guard: docs/reference/cli.md documents the `confiture sync` command.

Medium 3 (production data sync) was wired as a real top-level CLI command; this
guard pins that the CLI reference carries a `confiture sync` section and that
every long option the live Typer command registers is documented there — so the
reference can't drift from the implementation (a new/renamed flag fails here).
"""

from __future__ import annotations

import re

from doc_snippets import read_doc
from typer.testing import CliRunner

from confiture.cli.main import app

CLI_DOC = "docs/reference/cli.md"
runner = CliRunner()


def _sync_section(text: str) -> str:
    """The `## \\`confiture sync\\`` section body, up to the next `## ` heading."""
    marker = "## `confiture sync`"
    start = text.index(marker)
    end = text.find("\n## ", start + len(marker))
    return text[start:end] if end != -1 else text[start:]


def _live_long_flags() -> set[str]:
    """Every long option the live `sync` command exposes (minus --help)."""
    result = runner.invoke(app, ["sync", "--help"])
    assert result.exit_code == 0, result.output
    return {f for f in re.findall(r"--[a-z][a-z0-9-]*", result.output) if f != "--help"}


def test_doc_has_sync_section() -> None:
    assert "## `confiture sync`" in read_doc(CLI_DOC), "cli.md has no `confiture sync` section"


def test_every_live_flag_is_documented() -> None:
    """Each long flag the CLI registers is named in the sync reference section."""
    section = _sync_section(read_doc(CLI_DOC))
    missing = [flag for flag in _live_long_flags() if flag not in section]
    assert not missing, f"cli.md sync section is missing flags: {sorted(missing)}"
