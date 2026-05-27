"""Tests for the machine-readable pattern catalog.

The catalog is exposed via :func:`confiture.core.idempotency.patterns.list_patterns`
and surfaces the same information through the
``confiture migrate validate --list-patterns`` CLI flag.
"""

from __future__ import annotations

from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.patterns import PATTERNS, list_patterns


class TestListPatternsShape:
    """Shape and field contracts for the catalog."""

    def test_returns_one_entry_per_pattern_definition(self):
        """Catalog has the same length as PATTERNS."""
        catalog = list_patterns()
        assert len(catalog) == len(PATTERNS)
        assert len(catalog) > 0

    def test_each_entry_has_required_fields(self):
        """Every entry has the documented 7 keys, nothing more."""
        catalog = list_patterns()
        expected = {
            "id",
            "description",
            "severity",
            "has_skip_regex",
            "skip_hint",
            "has_auto_fix",
            "template_fillable",
        }
        for entry in catalog:
            assert set(entry.keys()) == expected, entry

    def test_field_types(self):
        """Fields carry the expected types."""
        for entry in list_patterns():
            assert isinstance(entry["id"], str)
            assert isinstance(entry["description"], str)
            assert entry["severity"] in {"error", "info"}
            assert isinstance(entry["has_skip_regex"], bool)
            assert isinstance(entry["has_auto_fix"], bool)
            assert isinstance(entry["template_fillable"], bool)
            # skip_hint is either None or a human-friendly string
            assert entry["skip_hint"] is None or isinstance(entry["skip_hint"], str)

    def test_does_not_expose_regex_objects(self):
        """Regex objects must not leak into the catalog (not JSON-serialisable)."""
        import re

        for entry in list_patterns():
            for value in entry.values():
                assert not isinstance(value, re.Pattern), entry

    def test_ids_match_idempotency_pattern_enum(self):
        """Each entry's id is a valid IdempotencyPattern enum name."""
        valid_ids = {p.name for p in IdempotencyPattern}
        for entry in list_patterns():
            assert entry["id"] in valid_ids


class TestSkipRegexFlag:
    """``has_skip_regex`` reflects PatternDefinition.skip_regex is not None."""

    def test_has_skip_regex_matches_definition(self):
        """For each pattern, has_skip_regex == (skip_regex is not None)."""
        by_id = {entry["id"]: entry for entry in list_patterns()}
        for pdef in PATTERNS:
            entry = by_id[pdef.pattern.name]
            assert entry["has_skip_regex"] is (pdef.skip_regex is not None)

    def test_create_table_advertises_skip_regex(self):
        """CREATE_TABLE has a skip_regex (CREATE TABLE IF NOT EXISTS)."""
        by_id = {entry["id"]: entry for entry in list_patterns()}
        assert by_id["CREATE_TABLE"]["has_skip_regex"] is True

    def test_alter_table_add_constraint_check_has_no_skip_regex(self):
        """ALTER TABLE ADD CONSTRAINT CHECK has no simple skip — needs DO block."""
        by_id = {entry["id"]: entry for entry in list_patterns()}
        assert by_id["ALTER_TABLE_ADD_CONSTRAINT_CHECK"]["has_skip_regex"] is False


class TestHasAutoFix:
    """``has_auto_fix`` reads from the single source of truth (FIXABLE_PATTERNS)."""

    def test_has_auto_fix_marks_known_fixable_patterns(self):
        """Three patterns known to be fixable advertise auto-fix."""
        by_id = {entry["id"]: entry for entry in list_patterns()}
        for fixable_id in ("CREATE_TABLE", "CREATE_INDEX", "CREATE_EXTENSION"):
            assert by_id[fixable_id]["has_auto_fix"] is True, fixable_id

    def test_has_auto_fix_marks_known_unfixable_patterns(self):
        """Two patterns known to lack auto-fix do not advertise it."""
        by_id = {entry["id"]: entry for entry in list_patterns()}
        for unfixable_id in (
            "ALTER_TABLE_ADD_CONSTRAINT_CHECK",
            "ALTER_TABLE_RENAME_COLUMN",
        ):
            assert by_id[unfixable_id]["has_auto_fix"] is False, unfixable_id

    def test_has_auto_fix_matches_fixable_patterns_set(self):
        """Catalog's has_auto_fix is identical to FIXABLE_PATTERNS membership."""
        from confiture.core.idempotency.fixer import FIXABLE_PATTERNS

        for entry in list_patterns():
            pattern = IdempotencyPattern[entry["id"]]
            assert entry["has_auto_fix"] is (pattern in FIXABLE_PATTERNS), entry


class TestSkipHint:
    """``skip_hint`` is human-readable text (NOT a regex)."""

    def test_create_table_skip_hint_mentions_if_not_exists(self):
        """The skip hint is what users should write — readable English/SQL."""
        by_id = {entry["id"]: entry for entry in list_patterns()}
        hint = by_id["CREATE_TABLE"]["skip_hint"]
        assert hint is not None
        assert "IF NOT EXISTS" in hint.upper()

    def test_pattern_without_skip_regex_has_none_skip_hint(self):
        """When there's no skip_regex, skip_hint is None too."""
        by_id = {entry["id"]: entry for entry in list_patterns()}
        for entry in by_id.values():
            if entry["has_skip_regex"] is False:
                assert entry["skip_hint"] is None
