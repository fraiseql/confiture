"""README claims that a reader can act on are checked against the repository.

The JSON-schema sentence is the one this guard pins: the set of commands it names
as schema-backed must equal the set of commands that actually have a schema under
``docs/reference/json-schemas/``, and it may only say "every" command has one when
that is true for every command offering ``--format json``.
"""

from __future__ import annotations

import re
from pathlib import Path

from typer.main import get_command

from confiture.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[3]
README = REPO_ROOT / "README.md"
SCHEMAS = REPO_ROOT / "docs" / "reference" / "json-schemas"

# Schema files that describe a shared fragment rather than one command's payload.
FRAGMENT_SCHEMAS = frozenset({"error-envelope", "issue-object"})


def _json_capable_commands() -> set[str]:
    """Every leaf command that offers a ``--format`` option (JSON is one of its values)."""
    found: set[str] = set()

    def walk(cmd, path: list[str]) -> None:
        subs = getattr(cmd, "commands", None)
        if subs:
            for name, sub in subs.items():
                walk(sub, [*path, name])
            return
        for param in cmd.params:
            if "--format" in getattr(param, "opts", []):
                found.add(" ".join(path))

    walk(get_command(app), [])
    return found


def _schema_backed_commands() -> set[str]:
    """Commands named by the schema files (``migrate-validate-idempotent`` → ``migrate validate``)."""
    leaves = _json_capable_commands()
    backed: set[str] = set()
    for schema in SCHEMAS.glob("*.schema.json"):
        stem = schema.name.removesuffix(".schema.json")
        if stem.startswith("_") or stem in FRAGMENT_SCHEMAS:
            continue
        words = stem.split("-")
        # Longest leading word sequence that is a real command (with dashes re-joined
        # for commands such as ``validate-config`` and ``down-to``).
        for length in range(len(words), 0, -1):
            candidate_words = words[:length]
            for command in leaves:
                if command.replace(" ", "-") == "-".join(candidate_words):
                    backed.add(command)
                    break
            else:
                continue
            break
        else:
            raise AssertionError(f"{schema.name} names no existing command")
    return backed


def _schema_sentence() -> str:
    text = README.read_text(encoding="utf-8")
    match = re.search(r"^- .*JSON schema.*$", text, flags=re.MULTILINE)
    assert match, "README has no bullet about JSON schemas"
    return match.group(0)


def test_readme_does_not_claim_every_json_output_has_a_schema_unless_true() -> None:
    uncovered = _json_capable_commands() - _schema_backed_commands()
    sentence = _schema_sentence()
    if uncovered:
        assert not re.search(r"\b[Ee]very\b", sentence), (
            f"README says every JSON output has a schema, but {len(uncovered)} commands "
            f"have none: {sorted(uncovered)[:8]}…"
        )


def test_readme_names_exactly_the_schema_backed_commands() -> None:
    sentence = _schema_sentence()
    named = set(re.findall(r"`([a-z][a-z0-9 -]*)`", sentence))
    backed = _schema_backed_commands()
    # The sentence names top-level commands and the migrate leaves; paths are dropped.
    named = {n for n in named if not n.startswith(("python/", "docs/"))}
    assert named == backed, (
        f"README names {sorted(named - backed)} without a schema and omits "
        f"{sorted(backed - named)} which have one"
    )
