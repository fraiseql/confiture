"""Every command that writes JSON publishes the shape it writes.

A consumer that parses ``--format json`` builds on key names; without a published
schema those names rest on a ``to_dict`` nobody promised to keep. So each command
whose ``--format`` accepts ``json`` has a section in ``docs/reference/json-schemas.md``
linking a schema file that exists — or it is an alias of one that does, or it is
listed below with the reason it has none yet. That list only shrinks: an entry for a
command that now has a schema, or no longer writes JSON, fails.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import typer.main

from confiture.cli.main import app

REPO = Path(__file__).resolve().parents[3]
REFERENCE = REPO / "docs" / "reference" / "json-schemas.md"
SCHEMAS = REPO / "python" / "confiture" / "schemas"

#: Commands that write another documented command's payload, by that command.
ALIASES: dict[str, str] = {
    "migrate verify-checksums": "verify-checksums",
}

#: Commands that write JSON with no published schema yet, and why. Shrink-only.
WITHOUT_SCHEMA: dict[str, str] = {
    "bootstrap": "no schema yet",
    "debug cte": "no schema yet",
    "diff": "no schema yet",
    "install-helpers": "no schema yet",
    "migrate apply-as": "no schema yet",
    "migrate baseline": "no schema yet",
    "migrate fix-signatures": "no schema yet",
    "migrate generate": "no schema yet",
    "migrate schema-to-schema analyze": "no schema yet",
    "migrate schema-to-schema cleanup": "no schema yet",
    "migrate schema-to-schema migrate": "no schema yet",
    "migrate schema-to-schema migrate-table": "no schema yet",
    "migrate schema-to-schema setup": "no schema yet",
    "migrate schema-to-schema verify": "no schema yet",
    "seed apply": "no schema yet",
    "seed generate": "no schema yet",
    "seed validate": "no schema yet",
    "test-db clone": "no schema yet",
    "test-db drop": "no schema yet",
    "test-db list": "no schema yet",
    "test-db provision-template": "no schema yet",
    "test-db prune": "no schema yet",
    "test-db ram-setup": "no schema yet",
    "test-db status": "no schema yet",
    "validate-profile": "no schema yet",
}

_HEADING = re.compile(r"^### `confiture ([a-z0-9 -]+?)(?: <[^>]+>)?(?: --[^`]*)?`", re.MULTILINE)
_LINK = re.compile(r"\((?:\./)?json-schemas/([a-z0-9-]+\.schema\.json)\)")


def _allowed_formats(param: Any) -> tuple[str, ...]:
    """The values ``format_option`` restricts ``--format`` to, from its validator."""
    for cell in getattr(param.callback, "__closure__", None) or ():
        value = cell.cell_contents
        if isinstance(value, tuple) and value and all(isinstance(v, str) for v in value):
            return value
    return tuple(re.findall(r"\bjson\b", param.help or ""))


def json_commands() -> set[str]:
    found: set[str] = set()

    def walk(command: Any, path: list[str]) -> None:
        subcommands = getattr(command, "commands", None)
        if subcommands:
            for name, sub in subcommands.items():
                walk(sub, [*path, name])
            return
        for param in command.params:
            if "--format" in getattr(param, "opts", []) and "json" in _allowed_formats(param):
                found.add(" ".join(path))

    walk(typer.main.get_command(app), [])
    return found


def documented() -> dict[str, list[str]]:
    """Each documented command, with the schema files its section links."""
    text = REFERENCE.read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    matches = list(_HEADING.finditer(text))
    for match, following in zip(matches, [*matches[1:], None], strict=True):
        body = text[match.end() : following.start() if following else len(text)]
        sections.setdefault(match.group(1).strip(), []).extend(_LINK.findall(body))
    return sections


def test_every_json_command_is_documented_aliased_or_listed() -> None:
    covered = set(documented()) | set(ALIASES) | set(WITHOUT_SCHEMA)

    assert sorted(json_commands() - covered) == []


def test_every_documented_section_links_a_schema_that_exists() -> None:
    missing = {
        command: [name for name in names if not (SCHEMAS / name).is_file()] or "no link"
        for command, names in documented().items()
        if not names or any(not (SCHEMAS / name).is_file() for name in names)
    }

    assert missing == {}


def test_an_alias_names_a_documented_command() -> None:
    assert {a: t for a, t in ALIASES.items() if t not in documented()} == {}


def test_the_without_schema_list_only_shrinks() -> None:
    """An entry for a command that now has a section, or writes no JSON, is stale."""
    stale = {
        command
        for command in WITHOUT_SCHEMA
        if command in documented() or command not in json_commands()
    }

    assert stale == set()
