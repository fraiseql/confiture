"""Tests for UNION uncast NULL validation.

Phase 12, Cycle 3: Detect bare NULL values in UNION queries.
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


class TestUnionUncastNulls:
    """Test detection of uncast NULL values in UNION queries."""

    def test_detects_bare_null_in_union(self) -> None:
        """Test that bare NULL in UNION is detected."""
        seed_sql = """
        SELECT 1 as id, 'value' as name
        UNION ALL
        SELECT 2, NULL;
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        null_violations = [
            v for v in violations
            if v.pattern == PrepSeedPattern.UNION_UNCAST_NULL
        ]
        assert len(null_violations) >= 1
        assert "null" in null_violations[0].message.lower()

    def test_detects_multiple_bare_nulls(self) -> None:
        """Test that multiple bare NULLs are detected."""
        seed_sql = """
        SELECT 1, 'value', NULL
        UNION ALL
        SELECT 2, NULL, 'other';
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        null_violations = [
            v for v in violations
            if v.pattern == PrepSeedPattern.UNION_UNCAST_NULL
        ]
        assert len(null_violations) >= 2

    def test_does_not_flag_casted_nulls(self) -> None:
        """Test that NULL::type casts are not flagged."""
        seed_sql = """
        SELECT 1 as id, NULL::timestamp as created
        UNION ALL
        SELECT 2, '2024-01-01'::timestamp;
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        null_violations = [
            v for v in violations
            if v.pattern == PrepSeedPattern.UNION_UNCAST_NULL
        ]
        assert len(null_violations) == 0

    def test_does_not_flag_all_casted_nulls(self) -> None:
        """Test that UNION with all casted NULLs passes."""
        seed_sql = """
        SELECT NULL::uuid as id, NULL::varchar as name
        UNION ALL
        SELECT NULL::uuid, 'test'::varchar;
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        null_violations = [
            v for v in violations
            if v.pattern == PrepSeedPattern.UNION_UNCAST_NULL
        ]
        assert len(null_violations) == 0

    def test_detects_null_in_first_branch(self) -> None:
        """Test detection of NULL in first UNION branch."""
        seed_sql = """
        SELECT NULL as id, 'value' as name
        UNION ALL
        SELECT 1, 'other';
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        null_violations = [
            v for v in violations
            if v.pattern == PrepSeedPattern.UNION_UNCAST_NULL
        ]
        assert len(null_violations) >= 1

    def test_detects_null_in_middle_branches(self) -> None:
        """Test detection of NULL in middle UNION branches."""
        seed_sql = """
        SELECT 1 as id
        UNION ALL
        SELECT NULL
        UNION ALL
        SELECT 3;
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        null_violations = [
            v for v in violations
            if v.pattern == PrepSeedPattern.UNION_UNCAST_NULL
        ]
        assert len(null_violations) >= 1

    def test_violation_severity_is_error(self) -> None:
        """Test that uncast NULL violation is ERROR severity."""
        seed_sql = """
        SELECT 1
        UNION ALL
        SELECT NULL;
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        null_violations = [
            v for v in violations
            if v.pattern == PrepSeedPattern.UNION_UNCAST_NULL
        ]
        assert len(null_violations) >= 1
        assert null_violations[0].severity == ViolationSeverity.ERROR

    def test_violation_has_fix_suggestion(self) -> None:
        """Test that uncast NULL violation includes fix suggestion."""
        seed_sql = """
        SELECT 1 as id, NULL as created
        UNION ALL
        SELECT 2, '2024-01-01'::timestamp;
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        null_violations = [
            v for v in violations
            if v.pattern == PrepSeedPattern.UNION_UNCAST_NULL
        ]
        assert len(null_violations) >= 1
        assert null_violations[0].suggestion is not None
        assert "NULL::" in null_violations[0].suggestion

    def test_does_not_flag_non_union_nulls(self) -> None:
        """Test that NULL in non-UNION queries is not flagged."""
        seed_sql = "INSERT INTO users (id, email) VALUES (1, NULL);"
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        null_violations = [
            v for v in violations
            if v.pattern == PrepSeedPattern.UNION_UNCAST_NULL
        ]
        assert len(null_violations) == 0

    def test_case_insensitive_null_detection(self) -> None:
        """Test that null detection is case-insensitive."""
        seed_sql = """
        SELECT 1
        UNION ALL
        SELECT null;
        """
        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        null_violations = [
            v for v in violations
            if v.pattern == PrepSeedPattern.UNION_UNCAST_NULL
        ]
        assert len(null_violations) >= 1
