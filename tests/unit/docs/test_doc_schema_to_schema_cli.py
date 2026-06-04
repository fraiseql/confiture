"""Executable guard: docs/reference/cli.md documents the schema-to-schema group.

Phase 04 wired ``migrate schema-to-schema`` (Medium 4, FDW) as a real CLI group
but the CLI reference still had no section for it — a "shipped but undocumented"
gap. This guard pins that the reference lists the group and every one of its six
subcommands, and that the documented names exactly match the names the CLI app
actually registers (so the doc can't drift from the implementation).
"""

from __future__ import annotations

from doc_snippets import read_doc

from confiture.cli.schema_to_schema import schema_to_schema_app

CLI_DOC = "docs/reference/cli.md"

# The names the CLI actually registers, derived from the live Typer app.
_REGISTERED = sorted(c.name for c in schema_to_schema_app.registered_commands)
_EXPECTED = ["analyze", "cleanup", "migrate", "migrate-table", "setup", "verify"]


def test_registered_subcommands_are_the_expected_six() -> None:
    """Sanity-pin the live command set the doc must mirror."""
    assert _REGISTERED == _EXPECTED, _REGISTERED


def test_doc_has_a_schema_to_schema_section() -> None:
    text = read_doc(CLI_DOC)
    assert "schema-to-schema" in text, "cli.md has no schema-to-schema section"


def test_doc_lists_every_registered_subcommand() -> None:
    """Every subcommand the CLI registers is named in the reference doc."""
    text = read_doc(CLI_DOC)
    missing = [
        sub
        for sub in _REGISTERED
        if f"schema-to-schema {sub}" not in text
    ]
    assert not missing, f"cli.md schema-to-schema section is missing: {missing}"
