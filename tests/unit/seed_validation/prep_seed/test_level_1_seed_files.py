"""Tests for Level 1 - Seed file validation.

Cycles 1-3: Validates seed files for correct schema target, FK naming, UUID format.
"""

from __future__ import annotations

from confiture.core.seed_validation.prep_seed.level_1_seed_files import (
    Level1SeedValidator,
)
from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedPattern,
)


class TestLevel1SeedValidator:
    """Test Level 1 seed file validation."""

    def test_validator_initialization(self) -> None:
        """Can create a Level1SeedValidator."""
        validator = Level1SeedValidator()
        assert validator is not None

    def test_detects_seed_targeting_final_table(self) -> None:
        """Detects when seed INSERT targets final table instead of prep_seed."""
        seed_sql = """
        INSERT INTO catalog.tb_manufacturer (id, name)
        VALUES ('uuid-1', 'Acme Corp');
        """

        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(
            sql=seed_sql,
            file_path="db/seeds/prep/manufacturers.sql",
        )

        # Should detect that INSERT targets catalog instead of prep_seed
        assert any(v.pattern == PrepSeedPattern.PREP_SEED_TARGET_MISMATCH for v in violations)

    def test_passes_seed_targeting_prep_seed(self) -> None:
        """Valid seed file targeting prep_seed passes validation."""
        seed_sql = """
        INSERT INTO prep_seed.tb_manufacturer (id, name)
        VALUES ('uuid-1', 'Acme Corp');
        """

        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(
            sql=seed_sql,
            file_path="db/seeds/prep/manufacturers.sql",
        )

        # Should have no violations
        assert not any(v.pattern == PrepSeedPattern.PREP_SEED_TARGET_MISMATCH for v in violations)

    def test_detects_missing_fk_id_suffix(self) -> None:
        """Detects FK columns without _id suffix in prep_seed."""
        seed_sql = """
        INSERT INTO prep_seed.tb_product (id, fk_manufacturer, name)
        VALUES ('uuid-1', 'uuid-123', 'Widget');
        """

        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(
            sql=seed_sql,
            file_path="db/seeds/prep/products.sql",
        )

        # Should detect FK without _id suffix
        assert any(v.pattern == PrepSeedPattern.INVALID_FK_NAMING for v in violations)

    def test_passes_fk_with_id_suffix(self) -> None:
        """FK columns with _id suffix are valid."""
        seed_sql = """
        INSERT INTO prep_seed.tb_product (id, fk_manufacturer_id, name)
        VALUES ('uuid-1', 'uuid-123', 'Widget');
        """

        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(
            sql=seed_sql,
            file_path="db/seeds/prep/products.sql",
        )

        # Should have no FK naming violations
        assert not any(v.pattern == PrepSeedPattern.INVALID_FK_NAMING for v in violations)

    def test_detects_invalid_uuid_format(self) -> None:
        """Detects invalid UUID format in seed data."""
        seed_sql = """
        INSERT INTO prep_seed.tb_manufacturer (id, name)
        VALUES ('not-a-uuid', 'Acme Corp');
        """

        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(
            sql=seed_sql,
            file_path="db/seeds/prep/manufacturers.sql",
        )

        # Should detect invalid UUID
        assert any(v.pattern == PrepSeedPattern.INVALID_UUID_FORMAT for v in violations)

    def test_accepts_valid_uuid_v4(self) -> None:
        """Valid UUID v4 format is accepted."""
        seed_sql = """
        INSERT INTO prep_seed.tb_manufacturer (id, name)
        VALUES ('550e8400-e29b-41d4-a716-446655440000', 'Acme Corp');
        """

        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(
            sql=seed_sql,
            file_path="db/seeds/prep/manufacturers.sql",
        )

        # Should have no UUID format violations
        assert not any(v.pattern == PrepSeedPattern.INVALID_UUID_FORMAT for v in violations)

    def test_detects_multiple_seed_issues(self) -> None:
        """Can detect multiple issues in one seed file."""
        seed_sql = """
        INSERT INTO prep_seed.tb_product (id, fk_manufacturer, name)
        VALUES ('invalid-uuid', 'uuid-123', 'Widget');
        """

        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(
            sql=seed_sql,
            file_path="db/seeds/prep/products.sql",
        )

        patterns = {v.pattern for v in violations}
        # Should detect: invalid FK naming (no _id), invalid UUID
        assert PrepSeedPattern.INVALID_FK_NAMING in patterns
        assert PrepSeedPattern.INVALID_UUID_FORMAT in patterns

    def test_detects_union_null_type_mismatch(self) -> None:
        """Detects NULL vs NULL::type mismatch in UNION."""
        seed_sql = """
        INSERT INTO prep_seed.tb_events (id, created_at)
        SELECT '01511131-0000-0000-0000-000000000001'::uuid, NULL::timestamp
        UNION ALL
        SELECT '01511131-0000-0000-0000-000000000002'::uuid, NULL;
        """

        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(
            sql=seed_sql,
            file_path="db/seeds/prep/events.sql",
        )

        # Should detect UNION type mismatch
        union_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_TYPE_MISMATCH
        ]
        assert len(union_violations) == 1
        assert "NULL::timestamp" in union_violations[0].message
        assert "column 2" in union_violations[0].message

    def test_detects_union_all_variant(self) -> None:
        """Detects mismatches in UNION ALL (not just UNION)."""
        seed_sql = """
        INSERT INTO prep_seed.tb_test (id, val)
        SELECT 1, NULL::int
        UNION ALL
        SELECT 2, NULL;
        """

        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        union_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_TYPE_MISMATCH
        ]
        assert len(union_violations) == 1

    def test_passes_union_with_consistent_types(self) -> None:
        """Valid UNION with consistent NULL types passes."""
        seed_sql = """
        INSERT INTO prep_seed.tb_events (id, created_at)
        SELECT '01511131-0000-0000-0000-000000000001'::uuid, NULL::timestamp
        UNION ALL
        SELECT '01511131-0000-0000-0000-000000000002'::uuid, NULL::timestamp;
        """

        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        # Should have no UNION violations
        union_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_TYPE_MISMATCH
        ]
        assert len(union_violations) == 0

    def test_detects_multiple_union_branches(self) -> None:
        """Detects mismatches across 3+ UNION branches."""
        seed_sql = """
        INSERT INTO prep_seed.tb_test (id, val)
        SELECT 1, NULL::int
        UNION ALL
        SELECT 2, NULL
        UNION ALL
        SELECT 3, NULL::int;
        """

        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        # Should detect branch 2's mismatch (compared to branch 1)
        union_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_TYPE_MISMATCH
        ]
        assert len(union_violations) == 1
        assert "branch 2" in union_violations[0].message

    def test_skips_non_union_queries(self) -> None:
        """Non-UNION queries are skipped (performance check)."""
        seed_sql = """
        INSERT INTO prep_seed.tb_test (id, name)
        VALUES (1, 'test1'), (2, 'test2'), (3, 'test3');
        """

        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        # Should have no UNION violations
        union_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_TYPE_MISMATCH
        ]
        assert len(union_violations) == 0

    def test_detects_union_column_count_mismatch(self) -> None:
        """Detects when UNION branches have different column counts."""
        seed_sql = """
        INSERT INTO prep_seed.tb_test (id, val1, val2)
        SELECT 1, NULL::int, NULL::text
        UNION ALL
        SELECT 2, NULL::int;
        """

        validator = Level1SeedValidator()
        violations = validator.validate_seed_file(sql=seed_sql, file_path="test.sql")

        union_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.UNION_TYPE_MISMATCH
        ]
        assert len(union_violations) == 1
        assert "column" in union_violations[0].message.lower()
