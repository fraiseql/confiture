"""Tests for Level 5 - Full seed execution.

Cycles 5-8: Seed loading, resolution execution, NULL FK detection, data integrity.

Note: These are unit tests that mock the database.
Integration tests with real database go in tests/integration/.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from confiture.core.seed_validation.prep_seed.level_5_execution import (
    Level5ExecutionValidator,
)
from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedPattern,
    ViolationSeverity,
)


class TestLevel5ExecutionValidator:
    """Test Level 5 full seed execution validation."""

    def test_validator_initialization(self) -> None:
        """Can create a Level5ExecutionValidator."""
        validator = Level5ExecutionValidator()
        assert validator is not None

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.read_text")
    def test_validates_seed_loading_success(
        self,
        mock_read_text: MagicMock,
        mock_exists: MagicMock,
    ) -> None:
        """Validates successful seed loading into prep_seed."""
        # Mock file operations
        mock_exists.return_value = True
        mock_read_text.return_value = (
            "INSERT INTO prep_seed.tb_manufacturer (id, name) VALUES ('uuid-1', 'Acme');"
        )

        validator = Level5ExecutionValidator()

        # Mock database connection
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 10  # 10 rows loaded

        mock_conn.execute.return_value = mock_result

        violations = validator.load_seeds(
            connection=mock_conn,
            seed_files=["db/seeds/prep/manufacturers.sql"],
        )

        # Should succeed
        assert len(violations) == 0

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.read_text")
    def test_detects_seed_loading_failure(
        self,
        mock_read_text: MagicMock,
        mock_exists: MagicMock,
    ) -> None:
        """Detects errors during seed loading."""
        # Mock file operations
        mock_exists.return_value = True
        mock_read_text.return_value = "INSERT INTO prep_seed.tb_bad (id) VALUES ('uuid-1');"

        validator = Level5ExecutionValidator()

        # Mock database that fails
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("Syntax error in seed file")

        violations = validator.load_seeds(
            connection=mock_conn,
            seed_files=["db/seeds/prep/bad_file.sql"],
        )

        # Should detect error
        assert len(violations) > 0
        assert any(
            v.pattern == PrepSeedPattern.PREP_SEED_TARGET_MISMATCH or "Syntax" in v.message
            for v in violations
        )

    def test_executes_resolution_functions(self) -> None:
        """Executes resolution functions after seed loading."""
        validator = Level5ExecutionValidator()

        # Mock database
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("tb_manufacturer", 5),
            ("tb_category", 3),
        ]

        mock_conn.execute.return_value = mock_result

        violations = validator.execute_resolutions(
            connection=mock_conn,
            resolution_functions=[
                "fn_resolve_tb_manufacturer",
                "fn_resolve_tb_category",
            ],
        )

        # Should execute without errors
        assert len(violations) == 0

    def test_detects_null_fks_after_resolution(self) -> None:
        """Detects NULL foreign keys after resolution."""
        validator = Level5ExecutionValidator()

        # Mock database with NULL FKs
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("tb_product", "fk_manufacturer", 1),  # 1 NULL FK
            ("tb_product", "fk_category", 3),  # 3 NULL FKs
        ]

        mock_conn.execute.return_value = mock_result

        violations = validator.detect_null_fks(
            connection=mock_conn,
            tables=["tb_product", "tb_category"],
        )

        # Should detect NULL FKs
        assert any(v.pattern == PrepSeedPattern.NULL_FK_AFTER_RESOLUTION for v in violations)

        # Should describe impact
        null_violation = next(
            v for v in violations if v.pattern == PrepSeedPattern.NULL_FK_AFTER_RESOLUTION
        )
        assert "tb_product" in null_violation.message
        assert null_violation.severity == ViolationSeverity.CRITICAL

    def test_passes_when_no_null_fks(self) -> None:
        """Passes when all FK values are non-NULL."""
        validator = Level5ExecutionValidator()

        # Mock database with no NULL FKs
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []  # No NULL FKs found

        mock_conn.execute.return_value = mock_result

        violations = validator.detect_null_fks(
            connection=mock_conn,
            tables=["tb_product"],
        )

        # Should have no violations
        assert len(violations) == 0

    def test_detects_unique_constraint_violations(self) -> None:
        """Detects duplicate identifiers after resolution."""
        validator = Level5ExecutionValidator()

        # Mock database with duplicate identifiers
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("550e8400-e29b-41d4-a716-446655440000", 2),  # UUID appears twice
            ("550e8400-e29b-41d4-a716-446655440001", 3),  # UUID appears 3 times
        ]

        mock_conn.execute.return_value = mock_result

        violations = validator.detect_duplicate_identifiers(
            connection=mock_conn,
            tables=["tb_product"],
        )

        # Should detect duplicates
        assert any(v.pattern == PrepSeedPattern.UNIQUE_CONSTRAINT_VIOLATION for v in violations)

    def test_passes_when_no_duplicates(self) -> None:
        """Passes when all identifiers are unique."""
        validator = Level5ExecutionValidator()

        # Mock database with no duplicates
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []  # No duplicates

        mock_conn.execute.return_value = mock_result

        violations = validator.detect_duplicate_identifiers(
            connection=mock_conn,
            tables=["tb_product"],
        )

        # Should have no violations
        assert len(violations) == 0

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.read_text")
    def test_full_execution_cycle(
        self,
        mock_read_text: MagicMock,
        mock_exists: MagicMock,
    ) -> None:
        """Full execution cycle: load → resolve → validate."""
        # Mock file operations
        mock_exists.return_value = True
        mock_read_text.return_value = "INSERT INTO prep_seed.tb_product (id) VALUES ('uuid-1');"

        validator = Level5ExecutionValidator()

        # Mock database
        mock_conn = MagicMock()
        mock_load_result = MagicMock()
        mock_load_result.rowcount = 10

        mock_exec_result = MagicMock()
        mock_exec_result.fetchall.return_value = [("tb_product", 10)]

        mock_null_result = MagicMock()
        mock_null_result.fetchall.return_value = []  # No NULL FKs

        mock_dup_result = MagicMock()
        mock_dup_result.fetchall.return_value = []  # No duplicates

        # Setup mock to return different results for each call
        mock_conn.execute.side_effect = [
            mock_load_result,  # Load seeds
            mock_exec_result,  # Execute resolutions
            mock_null_result,  # Check NULL FKs
            mock_dup_result,  # Check duplicates
        ]

        violations = validator.execute_full_cycle(
            connection=mock_conn,
            seed_files=["db/seeds/prep/test.sql"],
            resolution_functions=["fn_resolve_tb_product"],
            tables=["tb_product"],
        )

        # Should succeed completely
        assert len(violations) == 0


class TestLevel5ConstraintValidation:
    """Test comprehensive constraint validation in Level 5."""

    def test_detects_not_null_constraint_violation(self) -> None:
        """Detects NOT NULL constraint violations."""
        validator = Level5ExecutionValidator()

        # Mock database with NOT NULL violations
        mock_conn = MagicMock()
        mock_result = MagicMock()
        # Returns: (table, column, count_nulls)
        mock_result.fetchall.return_value = [
            ("tb_product", "name", 3),  # 3 NULL values in required field
            ("tb_product", "created_at", 1),  # 1 NULL in created_at
        ]

        mock_conn.execute.return_value = mock_result

        violations = validator.detect_not_null_violations(
            connection=mock_conn,
            tables=["tb_product"],
        )

        # Should detect NOT NULL violations
        assert len(violations) > 0
        assert any("NOT NULL" in v.message for v in violations)
        assert all(v.severity == ViolationSeverity.CRITICAL for v in violations)

    def test_detects_check_constraint_violation(self) -> None:
        """Detects CHECK constraint violations."""
        validator = Level5ExecutionValidator()

        # Mock database with CHECK constraint violations
        mock_conn = MagicMock()
        mock_result = MagicMock()
        # Returns: (table, constraint, count_violations)
        mock_result.fetchall.return_value = [
            ("tb_product", "price_positive", 5),  # 5 rows with price <= 0
            ("tb_order", "qty_gt_zero", 2),  # 2 rows with qty <= 0
        ]

        mock_conn.execute.return_value = mock_result

        violations = validator.detect_check_constraint_violations(
            connection=mock_conn,
            tables=["tb_product", "tb_order"],
        )

        # Should detect CHECK violations
        assert len(violations) > 0
        assert any("CHECK" in v.message for v in violations)

    def test_detects_foreign_key_constraint_violation(self) -> None:
        """Detects foreign key constraint violations."""
        validator = Level5ExecutionValidator()

        # Mock database with FK violations (pointing to non-existent rows)
        mock_conn = MagicMock()
        mock_result = MagicMock()
        # Returns: (table, fk_column, referenced_table, count_violations)
        mock_result.fetchall.return_value = [
            ("tb_product", "fk_manufacturer", "tb_manufacturer", 3),
            ("tb_order", "fk_customer", "tb_customer", 1),
        ]

        mock_conn.execute.return_value = mock_result

        violations = validator.detect_fk_constraint_violations(
            connection=mock_conn,
            tables=["tb_product", "tb_order"],
        )

        # Should detect FK violations
        assert len(violations) > 0
        assert any("foreign key" in v.message.lower() for v in violations)

    def test_passes_when_all_constraints_satisfied(self) -> None:
        """Passes when all constraints are satisfied."""
        validator = Level5ExecutionValidator()

        # Mock database with no violations
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []  # No violations

        mock_conn.execute.return_value = mock_result

        # All constraint checks should pass
        not_null_violations = validator.detect_not_null_violations(
            connection=mock_conn,
            tables=["tb_product"],
        )
        assert len(not_null_violations) == 0

        check_violations = validator.detect_check_constraint_violations(
            connection=mock_conn,
            tables=["tb_product"],
        )
        assert len(check_violations) == 0

        fk_violations = validator.detect_fk_constraint_violations(
            connection=mock_conn,
            tables=["tb_product"],
        )
        assert len(fk_violations) == 0

    def test_comprehensive_execution_with_constraint_checks(self) -> None:
        """Full execution with comprehensive constraint validation."""
        validator = Level5ExecutionValidator()

        # Mock file operations
        with (
            patch("pathlib.Path.exists") as mock_exists,
            patch("pathlib.Path.read_text") as mock_read_text,
        ):
            mock_exists.return_value = True
            mock_read_text.return_value = "INSERT INTO prep_seed.tb_product (id) VALUES ('uuid-1');"

            # Mock database
            mock_conn = MagicMock()

            # Setup results for each check
            mock_load = MagicMock()
            mock_exec = MagicMock()
            mock_exec.fetchall.return_value = [("tb_product", 10)]
            mock_null_fk = MagicMock()
            mock_null_fk.fetchall.return_value = []  # No NULL FKs
            mock_dup = MagicMock()
            mock_dup.fetchall.return_value = []  # No duplicates
            mock_not_null = MagicMock()
            mock_not_null.fetchall.return_value = []  # No NOT NULL violations
            mock_check = MagicMock()
            mock_check.fetchall.return_value = []  # No CHECK violations
            mock_fk = MagicMock()
            mock_fk.fetchall.return_value = []  # No FK violations

            mock_conn.execute.side_effect = [
                mock_load,  # Load seeds
                mock_exec,  # Execute resolutions
                mock_null_fk,  # Check NULL FKs
                mock_dup,  # Check duplicates
                mock_not_null,  # Check NOT NULL
                mock_check,  # Check CHECK constraints
                mock_fk,  # Check FK constraints
            ]

            violations = validator.execute_full_cycle_comprehensive(
                connection=mock_conn,
                seed_files=["db/seeds/prep/test.sql"],
                resolution_functions=["fn_resolve_tb_product"],
                tables=["tb_product"],
            )

            # All checks should pass
            assert len(violations) == 0
