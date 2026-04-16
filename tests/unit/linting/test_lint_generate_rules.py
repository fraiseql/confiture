"""Unit tests for GEN001–GEN004 lint rules — Phase 5 of issue #111.

All tests use pytest's ``tmp_path`` fixture.  No database required.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.linting.libraries.generate import (
    Gen001PrefixUnique,
    Gen002VerbSuffix,
    Gen003GapPolicy,
    Gen004OrphanedOverride,
)
from confiture.core.linting.schema_linter import RuleSeverity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _touch(directory: Path, *names: str) -> None:
    """Create empty .sql files under directory."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).touch()


def _violation_ids(violations: list) -> list[str]:
    return [v.rule_id for v in violations]


def _violation_files(violations: list) -> list[str]:
    return [v.file_path or "" for v in violations]


# ---------------------------------------------------------------------------
# GEN001 — Prefix uniqueness within a subtree
# ---------------------------------------------------------------------------


class TestGen001PrefixUnique:
    """Tests for GEN001: no two files in the same directory share a numeric prefix."""

    def test_no_violation_when_all_unique(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_create.sql", "00002_update.sql", "00003_delete.sql")

        violations = Gen001PrefixUnique().check(schema)

        assert violations == []

    def test_detects_duplicate_prefix(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_create.sql", "00001_update.sql")

        violations = Gen001PrefixUnique().check(schema)

        assert len(violations) == 1
        assert all(v.rule_id == "GEN001" for v in violations)

    def test_violation_severity_is_error(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_create.sql", "00001_update.sql")

        violations = Gen001PrefixUnique().check(schema)

        assert violations[0].severity == RuleSeverity.ERROR

    def test_three_files_same_prefix_two_violations(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_a.sql", "00001_b.sql", "00001_c.sql")

        violations = Gen001PrefixUnique().check(schema)

        assert len(violations) == 2

    def test_scans_subdirectories(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        sub = schema / "functions"
        _touch(schema, "00001_root.sql")
        _touch(sub, "00001_create.sql", "00001_update.sql")

        violations = Gen001PrefixUnique().check(schema)

        # Collision is in the subdirectory
        assert len(violations) == 1
        assert "functions" in (violations[0].file_path or "")

    def test_no_violation_for_files_without_prefix(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "create.sql", "update.sql", "README.md")

        violations = Gen001PrefixUnique().check(schema)

        assert violations == []

    def test_no_violation_across_different_directories(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema / "catalog", "00001_create.sql")
        _touch(schema / "public", "00001_create.sql")

        violations = Gen001PrefixUnique().check(schema)

        # Same prefix is fine if they're in different directories
        assert violations == []

    def test_hex_prefix_collision_detected(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "0001a_create.sql", "0001a_update.sql")

        violations = Gen001PrefixUnique().check(schema)

        assert len(violations) == 1


# ---------------------------------------------------------------------------
# GEN002 — Verb suffix
# ---------------------------------------------------------------------------


class TestGen002VerbSuffix:
    """Tests for GEN002: prefixed filenames must include a verb suffix."""

    def test_no_violation_for_verb_files(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_create.sql", "00002_update.sql")

        violations = Gen002VerbSuffix().check(schema)

        assert violations == []

    def test_detects_prefix_only_file(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001.sql")

        violations = Gen002VerbSuffix().check(schema)

        assert len(violations) == 1
        assert violations[0].rule_id == "GEN002"

    def test_violation_severity_is_warning(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001.sql")

        violations = Gen002VerbSuffix().check(schema)

        assert violations[0].severity == RuleSeverity.WARNING

    def test_no_violation_for_unprefixed_files(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "helpers.sql", "seed.sql")

        violations = Gen002VerbSuffix().check(schema)

        assert violations == []

    def test_scans_subdirectories(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema / "functions", "00001.sql")

        violations = Gen002VerbSuffix().check(schema)

        assert len(violations) == 1

    def test_multiple_violations_reported(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001.sql", "00002.sql", "00003_ok.sql")

        violations = Gen002VerbSuffix().check(schema)

        assert len(violations) == 2

    def test_hex_prefix_only_file_flagged(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "0001a.sql")

        violations = Gen002VerbSuffix().check(schema)

        assert len(violations) == 1


# ---------------------------------------------------------------------------
# GEN003 — Gap policy
# ---------------------------------------------------------------------------


class TestGen003GapPolicy:
    """Tests for GEN003: warn on gaps in prefix sequences."""

    def test_no_violation_for_contiguous_sequence(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_a.sql", "00002_b.sql", "00003_c.sql")

        violations = Gen003GapPolicy().check(schema)

        assert violations == []

    def test_detects_gap_in_sequence(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_a.sql", "00003_c.sql")

        violations = Gen003GapPolicy().check(schema)

        assert len(violations) == 1
        assert violations[0].rule_id == "GEN003"

    def test_violation_severity_is_warning(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_a.sql", "00005_e.sql")

        violations = Gen003GapPolicy().check(schema)

        assert violations[0].severity == RuleSeverity.WARNING

    def test_no_violation_for_single_file(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_only.sql")

        violations = Gen003GapPolicy().check(schema)

        assert violations == []

    def test_no_violation_for_empty_dir(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()

        violations = Gen003GapPolicy().check(schema)

        assert violations == []

    def test_multiple_gaps_reported(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_a.sql", "00003_c.sql", "00007_g.sql")

        violations = Gen003GapPolicy().check(schema)

        assert len(violations) == 2

    def test_scans_subdirectories_independently(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        # Root: contiguous
        _touch(schema, "00001_a.sql", "00002_b.sql")
        # Sub: has gap
        _touch(schema / "functions", "00001_x.sql", "00003_z.sql")

        violations = Gen003GapPolicy().check(schema)

        assert len(violations) == 1
        assert "functions" in (violations[0].file_path or "")

    def test_no_violation_for_unprefixed_files(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "alpha.sql", "beta.sql")

        violations = Gen003GapPolicy().check(schema)

        assert violations == []


# ---------------------------------------------------------------------------
# GEN004 — Orphaned overrides
# ---------------------------------------------------------------------------


class TestGen004OrphanedOverride:
    """Tests for GEN004: no override file without a matching schema file."""

    def test_no_violation_when_all_matched(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        overrides = tmp_path / "overrides"
        _touch(schema / "functions", "00001_create.sql")
        _touch(overrides / "functions", "00001_create.sql")

        violations = Gen004OrphanedOverride().check(schema, overrides)

        assert violations == []

    def test_detects_orphaned_override(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "overrides"
        _touch(overrides / "functions", "00001_create.sql")
        # No matching file in schema/functions/

        violations = Gen004OrphanedOverride().check(schema, overrides)

        assert len(violations) == 1
        assert violations[0].rule_id == "GEN004"

    def test_violation_severity_is_warning(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "overrides"
        _touch(overrides, "00001_create.sql")

        violations = Gen004OrphanedOverride().check(schema, overrides)

        assert violations[0].severity == RuleSeverity.WARNING

    def test_no_violation_when_overrides_dir_missing(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "nonexistent_overrides"

        violations = Gen004OrphanedOverride().check(schema, overrides)

        assert violations == []

    def test_multiple_orphans_reported(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "overrides"
        _touch(overrides, "00001_a.sql", "00002_b.sql")

        violations = Gen004OrphanedOverride().check(schema, overrides)

        assert len(violations) == 2

    def test_nested_orphan_detected(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "overrides"
        _touch(overrides / "catalog" / "manufacturer", "00001_create.sql")

        violations = Gen004OrphanedOverride().check(schema, overrides)

        assert len(violations) == 1

    def test_non_sql_files_in_overrides_ignored(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "overrides"
        overrides.mkdir()
        (overrides / "README.md").touch()

        violations = Gen004OrphanedOverride().check(schema, overrides)

        assert violations == []


# ---------------------------------------------------------------------------
# SchemaLinter.lint_tree() integration
# ---------------------------------------------------------------------------


class TestSchemaLinterLintTree:
    """Integration tests for SchemaLinter.lint_tree()."""

    def test_lint_tree_returns_report(self, tmp_path: Path) -> None:
        from confiture.core.linting.schema_linter import LintReport, SchemaLinter

        schema = tmp_path / "schema"
        schema.mkdir()

        report = SchemaLinter().lint_tree(schema)

        assert isinstance(report, LintReport)

    def test_lint_tree_collects_all_rule_violations(self, tmp_path: Path) -> None:
        from confiture.core.linting.schema_linter import SchemaLinter

        schema = tmp_path / "schema"
        # GEN001: duplicate prefix
        _touch(schema, "00001_a.sql", "00001_b.sql")
        # GEN002: no verb
        _touch(schema, "00002.sql")
        # GEN003: gap
        _touch(schema, "00010_x.sql")

        report = SchemaLinter().lint_tree(schema)

        all_ids = {v.rule_id for v in report.errors + report.warnings + report.info}
        assert "GEN001" in all_ids
        assert "GEN002" in all_ids
        assert "GEN003" in all_ids

    def test_lint_tree_includes_gen004_when_overrides_dir_given(self, tmp_path: Path) -> None:
        from confiture.core.linting.schema_linter import SchemaLinter

        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "overrides"
        _touch(overrides, "00001_orphan.sql")

        report = SchemaLinter().lint_tree(schema, overrides_dir=overrides)

        all_ids = {v.rule_id for v in report.errors + report.warnings + report.info}
        assert "GEN004" in all_ids

    def test_lint_tree_clean_schema_no_violations(self, tmp_path: Path) -> None:
        from confiture.core.linting.schema_linter import SchemaLinter

        schema = tmp_path / "schema"
        _touch(schema, "00001_create.sql", "00002_update.sql", "00003_delete.sql")

        report = SchemaLinter().lint_tree(schema)

        assert report.total_violations == 0
