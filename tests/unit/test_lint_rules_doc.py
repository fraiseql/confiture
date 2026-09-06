"""The published rule reference is generated from the registry (Phase 07).

``docs/reference/lint-rules.md`` embeds ``render_rule_table()`` between
generated-section markers, exactly as the error codebook does; a rule added
to ``LINT_RULES`` without regenerating the page fails here.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.linting.rule_registry import LINT_RULES, render_rule_table

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC = _REPO_ROOT / "docs" / "reference" / "lint-rules.md"


def test_rule_table_embeds_the_current_registry() -> None:
    doc = _DOC.read_text()
    begin = "<!-- BEGIN GENERATED: lint-rules -->"
    end = "<!-- END GENERATED -->"
    assert begin in doc and end in doc, "lint-rules.md generated-section markers missing"
    embedded = doc.split(begin, 1)[1].split(end, 1)[0].strip()
    assert embedded == render_rule_table().strip(), (
        "lint-rules.md is stale; regenerate from render_rule_table()"
    )


def test_every_registered_rule_is_on_the_page() -> None:
    doc = _DOC.read_text()
    missing = [rule.code for rule in LINT_RULES if f"`{rule.code}`" not in doc]
    assert missing == [], f"rules missing from lint-rules.md: {missing}"
