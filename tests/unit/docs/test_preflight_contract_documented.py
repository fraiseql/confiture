"""The preflight's contract on `up()` is written down somewhere a user reads (#311).

`confiture migrate preflight` executes real `up()` bodies, and confiture's own
help recommends a schema-only database for it twice
(`cli/commands/migrate/preflight.py`). `--against` accepts any DSN, so the
topology is recommended and not enforced — which makes "up() must survive empty
tables" an obligation the user inherits.

Recommending a topology while leaving its obligation unwritten is the defect
this issue is about. Before 1.12.0 it was unwritten everywhere: not in the
generated template, not in `migrate validate`'s ~35 check flags, and in no
guide. `.verify.sql` — the mechanism that makes the obligation easy to satisfy
— appeared only in `docs/reference/`, two JSON schemas and docstrings.

A guide, not only a reference page: reference is where you look something up
once you know its name, and not knowing the name was the whole problem.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GUIDES = ROOT / "docs" / "guides"


@pytest.fixture(scope="module")
def guide_texts() -> dict[Path, str]:
    return {p: p.read_text() for p in sorted(GUIDES.glob("*.md"))}


def _guides_naming(guide_texts: dict[Path, str], needle: str) -> list[str]:
    return [p.name for p, text in guide_texts.items() if needle in text]


def test_a_guide_names_the_sidecar(guide_texts: dict[Path, str]) -> None:
    assert _guides_naming(guide_texts, ".verify.sql"), "no guide mentions .verify.sql"


def test_a_guide_states_the_schema_only_obligation(guide_texts: dict[Path, str]) -> None:
    named = set(_guides_naming(guide_texts, "schema-only")) & set(
        _guides_naming(guide_texts, "preflight")
    )
    assert named, "no guide explains what `migrate preflight` runs up() against"


def test_a_guide_names_verify_checksums(guide_texts: dict[Path, str]) -> None:
    """The command appeared in no guide either — only reference and runbook pages."""
    assert _guides_naming(guide_texts, "verify-checksums"), "no guide mentions verify-checksums"


def test_one_guide_covers_the_whole_question(guide_texts: dict[Path, str]) -> None:
    """Scattered across three guides, the contract is still not readable in one go."""
    whole = [
        p.name
        for p, text in guide_texts.items()
        if all(n in text for n in (".verify.sql", "schema-only", "preflight", "migrate verify"))
    ]
    assert whole, "no single guide covers preflight's topology and where assertions belong"


def test_the_guide_is_in_the_nav(guide_texts: dict[Path, str]) -> None:
    """A page mkdocs does not list is a page nobody browses to."""
    nav = (ROOT / "mkdocs.yml").read_text()
    for name in _guides_naming(guide_texts, ".verify.sql"):
        assert f"guides/{name}" in nav, f"{name} is not in mkdocs.yml nav"
