"""Unit tests for the tree_001–tree_004 file-tree lint rules — issue #111.

All tests use pytest's ``tmp_path`` fixture.  No database required.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.linting.libraries.generate import (
    Tree001PrefixUnique,
    Tree002VerbSuffix,
    Tree003GapPolicy,
    Tree004OrphanedOverride,
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


def _files(directory: Path) -> list[Path]:
    """The SQL files under *directory*, standing in for what the build would read."""
    return sorted(f for f in directory.rglob("*.sql") if f.is_file())


def _violation_ids(violations: list) -> list[str]:
    return [v.rule_id for v in violations]


def _violation_files(violations: list) -> list[str]:
    return [v.file_path or "" for v in violations]


# ---------------------------------------------------------------------------
# tree_001 — Prefix uniqueness within a subtree
# ---------------------------------------------------------------------------


class TestTree001PrefixUnique:
    """Tests for tree_001: no two files in the same directory share a numeric prefix."""

    def test_no_violation_when_all_unique(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_create.sql", "00002_update.sql", "00003_delete.sql")

        violations = Tree001PrefixUnique().check(_files(schema))

        assert violations == []

    def test_detects_duplicate_prefix(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_create.sql", "00001_update.sql")

        violations = Tree001PrefixUnique().check(_files(schema))

        assert len(violations) == 1
        assert all(v.rule_id == "tree_001" for v in violations)

    def test_violation_severity_is_error(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_create.sql", "00001_update.sql")

        violations = Tree001PrefixUnique().check(_files(schema))

        assert violations[0].severity == RuleSeverity.ERROR

    def test_three_files_same_prefix_two_violations(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_a.sql", "00001_b.sql", "00001_c.sql")

        violations = Tree001PrefixUnique().check(_files(schema))

        assert len(violations) == 2

    def test_scans_subdirectories(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        sub = schema / "functions"
        _touch(schema, "00001_root.sql")
        _touch(sub, "00001_create.sql", "00001_update.sql")

        violations = Tree001PrefixUnique().check(_files(schema))

        # Collision is in the subdirectory
        assert len(violations) == 1
        assert "functions" in (violations[0].file_path or "")

    def test_no_violation_for_files_without_prefix(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "create.sql", "update.sql", "README.md")

        violations = Tree001PrefixUnique().check(_files(schema))

        assert violations == []

    def test_no_violation_across_different_directories(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema / "catalog", "00001_create.sql")
        _touch(schema / "public", "00001_create.sql")

        violations = Tree001PrefixUnique().check(_files(schema))

        # Same prefix is fine if they're in different directories
        assert violations == []

    def test_hex_prefix_collision_detected(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "0001a_create.sql", "0001a_update.sql")

        violations = Tree001PrefixUnique().check(_files(schema))

        assert len(violations) == 1


# ---------------------------------------------------------------------------
# tree_002 — Verb suffix
# ---------------------------------------------------------------------------


class TestTree002VerbSuffix:
    """Tests for tree_002: prefixed filenames must include a verb suffix."""

    def test_no_violation_for_verb_files(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_create.sql", "00002_update.sql")

        violations = Tree002VerbSuffix().check(_files(schema))

        assert violations == []

    def test_detects_prefix_only_file(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001.sql")

        violations = Tree002VerbSuffix().check(_files(schema))

        assert len(violations) == 1
        assert violations[0].rule_id == "tree_002"

    def test_violation_severity_is_warning(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001.sql")

        violations = Tree002VerbSuffix().check(_files(schema))

        assert violations[0].severity == RuleSeverity.WARNING

    def test_no_violation_for_unprefixed_files(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "helpers.sql", "seed.sql")

        violations = Tree002VerbSuffix().check(_files(schema))

        assert violations == []

    def test_scans_subdirectories(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema / "functions", "00001.sql")

        violations = Tree002VerbSuffix().check(_files(schema))

        assert len(violations) == 1

    def test_multiple_violations_reported(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001.sql", "00002.sql", "00003_ok.sql")

        violations = Tree002VerbSuffix().check(_files(schema))

        assert len(violations) == 2

    def test_hex_prefix_only_file_flagged(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "0001a.sql")

        violations = Tree002VerbSuffix().check(_files(schema))

        assert len(violations) == 1


# ---------------------------------------------------------------------------
# tree_003 — Gap policy
# ---------------------------------------------------------------------------


class TestTree003GapPolicy:
    """Tests for tree_003: warn on gaps in prefix sequences."""

    def test_no_violation_for_contiguous_sequence(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_a.sql", "00002_b.sql", "00003_c.sql")

        violations = Tree003GapPolicy().check(_files(schema))

        assert violations == []

    def test_detects_gap_in_sequence(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_a.sql", "00003_c.sql")

        violations = Tree003GapPolicy().check(_files(schema))

        assert len(violations) == 1
        assert violations[0].rule_id == "tree_003"

    def test_violation_severity_is_warning(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_a.sql", "00005_e.sql")

        violations = Tree003GapPolicy().check(_files(schema))

        assert violations[0].severity == RuleSeverity.WARNING

    def test_no_violation_for_single_file(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_only.sql")

        violations = Tree003GapPolicy().check(_files(schema))

        assert violations == []

    def test_no_violation_for_empty_dir(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()

        violations = Tree003GapPolicy().check(_files(schema))

        assert violations == []

    def test_multiple_gaps_reported(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "00001_a.sql", "00003_c.sql", "00007_g.sql")

        violations = Tree003GapPolicy().check(_files(schema))

        assert len(violations) == 2

    def test_scans_subdirectories_independently(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        # The root directory numbering is contiguous.
        _touch(schema, "00001_a.sql", "00002_b.sql")
        # Sub: has gap
        _touch(schema / "functions", "00001_x.sql", "00003_z.sql")

        violations = Tree003GapPolicy().check(_files(schema))

        assert len(violations) == 1
        assert "functions" in (violations[0].file_path or "")

    def test_no_violation_for_unprefixed_files(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        _touch(schema, "alpha.sql", "beta.sql")

        violations = Tree003GapPolicy().check(_files(schema))

        assert violations == []


# ---------------------------------------------------------------------------
# tree_004 — Orphaned overrides
# ---------------------------------------------------------------------------


class TestTree004OrphanedOverride:
    """Tests for tree_004: no override file without a matching schema file."""

    def test_no_violation_when_all_matched(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        overrides = tmp_path / "overrides"
        _touch(schema / "functions", "00001_create.sql")
        _touch(overrides / "functions", "00001_create.sql")

        violations = Tree004OrphanedOverride().check([schema], overrides)

        assert violations == []

    def test_detects_orphaned_override(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "overrides"
        _touch(overrides / "functions", "00001_create.sql")
        # No matching file in schema/functions/

        violations = Tree004OrphanedOverride().check([schema], overrides)

        assert len(violations) == 1
        assert violations[0].rule_id == "tree_004"

    def test_violation_severity_is_warning(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "overrides"
        _touch(overrides, "00001_create.sql")

        violations = Tree004OrphanedOverride().check([schema], overrides)

        assert violations[0].severity == RuleSeverity.WARNING

    def test_no_violation_when_overrides_dir_missing(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "nonexistent_overrides"

        violations = Tree004OrphanedOverride().check([schema], overrides)

        assert violations == []

    def test_multiple_orphans_reported(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "overrides"
        _touch(overrides, "00001_a.sql", "00002_b.sql")

        violations = Tree004OrphanedOverride().check([schema], overrides)

        assert len(violations) == 2

    def test_nested_orphan_detected(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "overrides"
        _touch(overrides / "catalog" / "manufacturer", "00001_create.sql")

        violations = Tree004OrphanedOverride().check([schema], overrides)

        assert len(violations) == 1

    def test_non_sql_files_in_overrides_ignored(self, tmp_path: Path) -> None:
        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "overrides"
        overrides.mkdir()
        (overrides / "README.md").touch()

        violations = Tree004OrphanedOverride().check([schema], overrides)

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
        # tree_001: duplicate prefix
        _touch(schema, "00001_a.sql", "00001_b.sql")
        # tree_002: no verb
        _touch(schema, "00002.sql")
        # tree_003 fires on the gap that follows.
        _touch(schema, "00010_x.sql")

        report = SchemaLinter().lint_tree(schema)

        all_ids = {v.rule_id for v in report.errors + report.warnings + report.info}
        assert "tree_001" in all_ids
        assert "tree_002" in all_ids
        assert "tree_003" in all_ids

    def test_lint_tree_includes_tree_004_when_overrides_dir_given(self, tmp_path: Path) -> None:
        from confiture.core.linting.schema_linter import SchemaLinter

        schema = tmp_path / "schema"
        schema.mkdir()
        overrides = tmp_path / "overrides"
        _touch(overrides, "00001_orphan.sql")

        report = SchemaLinter().lint_tree(schema, overrides_dir=overrides)

        all_ids = {v.rule_id for v in report.errors + report.warnings + report.info}
        assert "tree_004" in all_ids

    def test_lint_tree_clean_schema_no_violations(self, tmp_path: Path) -> None:
        from confiture.core.linting.schema_linter import SchemaLinter

        schema = tmp_path / "schema"
        _touch(schema, "00001_create.sql", "00002_update.sql", "00003_delete.sql")

        report = SchemaLinter().lint_tree(schema)

        assert report.total_violations == 0
