"""Executable guard: documentation config examples load through the real loader.

DOCS-C1 anti-drift guard. The canonical "Complete Example" in
``docs/reference/configuration.md`` must validate against the same
``Environment`` model that ``Migrator.from_config()`` uses — so a config a
reader copies verbatim actually works. The legacy top-level ``migration_table``
key (rejected by ``_reject_legacy_migration_table``) must never reappear.
"""

from __future__ import annotations

import yaml
from doc_snippets import fenced_after_anchor, read_doc

from confiture.config.environment import Environment

CONFIG_DOC = "docs/reference/configuration.md"


def test_complete_example_validates_through_real_loader() -> None:
    """The 'Complete Example' YAML loads cleanly via Environment.model_validate."""
    snippet = fenced_after_anchor(read_doc(CONFIG_DOC), "config-complete-example")
    data = yaml.safe_load(snippet)

    # Must not raise ConfigurationError / ValidationError.
    env = Environment.model_validate(data)

    # And it must actually exercise the tracking-table config (the field the
    # old fictional `migration_table` key was pretending to set).
    assert env.migration.tracking_table


def test_complete_example_uses_nested_tracking_table_not_legacy_key() -> None:
    """The canonical example uses migration.tracking_table, not legacy migration_table."""
    snippet = fenced_after_anchor(read_doc(CONFIG_DOC), "config-complete-example")
    data = yaml.safe_load(snippet)

    assert "migration_table" not in data, (
        "Doc example uses the legacy top-level 'migration_table' key, which the "
        "loader rejects. Use nested 'migration: { tracking_table: ... }'."
    )
    assert "tracking_table" in data.get("migration", {})
