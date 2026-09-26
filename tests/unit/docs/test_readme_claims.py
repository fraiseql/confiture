"""README claims that a reader can act on are checked against the repository.

The JSON-schema sentence is the one this guard pins: it may only say "every"
command has a schema when every command offering ``--format json`` has one, by the
answer ``tests/unit/json_schemas/test_every_json_command_has_a_schema.py`` gives.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.json_schemas.test_every_json_command_has_a_schema import (
    ALIASES,
    documented,
    json_commands,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
README = REPO_ROOT / "README.md"


def _schema_sentence() -> str:
    text = README.read_text(encoding="utf-8")
    match = re.search(r"^- .*JSON schema.*$", text, flags=re.MULTILINE)
    assert match, "README has no bullet about JSON schemas"
    return match.group(0)


def test_readme_does_not_claim_every_json_output_has_a_schema_unless_true() -> None:
    # The guard's own answer, so the README and the guard cannot disagree.
    uncovered = json_commands() - set(documented()) - set(ALIASES)
    sentence = _schema_sentence()
    if uncovered:
        assert not re.search(r"\b[Ee]very\b", sentence), (
            f"README says every JSON output has a schema, but {len(uncovered)} commands "
            f"have none: {sorted(uncovered)[:8]}…"
        )
