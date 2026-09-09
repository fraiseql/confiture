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


def _hand_written_include_dirs_table() -> dict[str, str]:
    """The `include_dirs` options table a reader sees, as ``{field: default}``.

    ``configuration.md`` carries this table by hand *and* a generated one for
    the same model further down. Two tables in one file is how the
    ``auto_discover`` default came to be documented as ``false`` when the model
    says ``true``, and the `order` default as ``auto`` when it is ``0``.
    """
    text = read_doc(CONFIG_DOC)
    body = text.split("**Configuration Options**:", 1)[1].split("**Path resolution**", 1)[0]
    defaults: dict[str, str] = {}
    for line in body.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or not cells[0].startswith("`"):
            continue
        defaults[cells[0].strip("`")] = cells[2]
    return defaults


def test_include_dirs_table_matches_the_model() -> None:
    """Every default in the hand-written table is the one ``DirectoryConfig`` has."""
    from confiture.config.environment import DirectoryConfig

    documented = _hand_written_include_dirs_table()
    assert documented, "the include_dirs options table is no longer where this test looks"

    fields = DirectoryConfig.model_fields
    assert set(documented) == set(fields), (
        f"table and model disagree about the fields: {set(documented) ^ set(fields)}"
    )

    wrong: list[str] = []
    for name, cell in documented.items():
        field = fields[name]
        if field.is_required():
            if cell != "required":
                wrong.append(f"{name}: table says {cell!r}, the field is required")
            continue
        actual = field.get_default(call_default_factory=True)
        expected = {True: "`true`", False: "`false`"}.get(
            actual if isinstance(actual, bool) else object(), f"`{actual!r}`".replace("'", '"')
        )
        if cell != expected:
            wrong.append(f"{name}: table says {cell!r}, the model says {expected!r}")
    assert wrong == [], "the hand-written table has drifted from the model:\n  " + "\n  ".join(
        wrong
    )
