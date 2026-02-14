"""Tests for UNION inline comment validation.

Issue #40
"""

from __future__ import annotations

from confiture.core.seed_validation.prep_seed.level_1_seed_files import (
    Level1SeedValidator,
)
from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedPattern,
    ViolationSeverity,
)


class TestUnionInlineComments:
    """Test detection of inline comments after UNION ALL."""

    def test_detects_inline_comment_after_union_all(self) -> None:
        """Test that inline comment after UNION ALL is detected."""
        seed_sql = """
        SELECT 1 as id, 'value1' as name
        UNION ALL -- This comment breaks concatenation
        SELECT 2, 'value2';
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        inline_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_INLINE_COMMENT
        ]
        assert len(inline_violations) == 1
        assert "comment" in inline_violations[0].message.lower()

    def test_detects_inline_comment_after_union(self) -> None:
        """Test that inline comment after UNION (without ALL) is detected."""
        seed_sql = """
        SELECT 1
        UNION -- comment without ALL
        SELECT 2;
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        inline_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_INLINE_COMMENT
        ]
        assert len(inline_violations) >= 1

    def test_detects_multiple_inline_comments(self) -> None:
        """Test that multiple inline comments are detected."""
        seed_sql = """
        SELECT 1
        UNION ALL -- comment 1
        SELECT 2
        UNION ALL -- comment 2
        SELECT 3;
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        inline_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_INLINE_COMMENT
        ]
        assert len(inline_violations) >= 2

    def test_detects_comment_with_special_chars(self) -> None:
        """Test that inline comment with special characters is detected."""
        seed_sql = """
        SELECT 1
        UNION ALL -- TODO: Fix this query!
        SELECT 2;
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        inline_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_INLINE_COMMENT
        ]
        assert len(inline_violations) >= 1

    def test_does_not_flag_comment_in_string(self) -> None:
        """Test that comment in string is not flagged."""
        seed_sql = """
        SELECT 1 as id, 'UNION ALL -- this is part of string' as note
        UNION ALL
        SELECT 2, 'another string';
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        # Should have no violations
        inline_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_INLINE_COMMENT
        ]
        # May have other violations but not inline comment
        assert len(inline_violations) == 0

    def test_does_not_flag_comment_on_different_line(self) -> None:
        """Test that comment on different line is not flagged as inline."""
        seed_sql = """
        SELECT 1
        -- This is a line comment
        UNION ALL
        SELECT 2;
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        inline_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_INLINE_COMMENT
        ]
        assert len(inline_violations) == 0

    def test_violation_has_fix_suggestion(self) -> None:
        """Test that violation includes fix suggestion."""
        seed_sql = """
        SELECT 1
        UNION ALL -- inline comment
        SELECT 2;
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        inline_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_INLINE_COMMENT
        ]
        assert len(inline_violations) >= 1
        assert inline_violations[0].suggestion is not None

    def test_violation_severity_is_warning(self) -> None:
        """Test that inline comment violation is WARNING severity."""
        seed_sql = """
        SELECT 1
        UNION ALL -- comment
        SELECT 2;
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        inline_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_INLINE_COMMENT
        ]
        assert len(inline_violations) >= 1
        assert inline_violations[0].severity == ViolationSeverity.WARNING

    def test_no_false_positives_for_simple_union(self) -> None:
        """Test that simple UNION without comments passes."""
        seed_sql = """
        SELECT 1 as id, 'Alice' as name
        UNION ALL
        SELECT 2, 'Bob';
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        inline_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_INLINE_COMMENT
        ]
        assert len(inline_violations) == 0
