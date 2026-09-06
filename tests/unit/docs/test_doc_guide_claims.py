"""Sentences in the guides that state what a flag does, pinned to the behaviour.

Each check names the guide, the sentence and the code fact it rests on, so a change to
either side lands here before it lands on a reader.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GUIDES = REPO_ROOT / "docs" / "guides"


def test_migrate_validate_guide_says_check_imports_imports_the_module() -> None:
    """``--check-imports`` executes ``importlib`` on each ``.py`` migration (Level 1); the guide must say so."""
    text = (GUIDES / "migrate-validate.md").read_text(encoding="utf-8")
    assert "`--check-imports` **imports each Python migration module**" in text, (
        "migrate-validate.md no longer states that --check-imports imports the module"
    )
