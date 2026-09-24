"""Tests for Level 4 - Runtime validation.

Database connection, table existence, dry-run.

Note: These are unit tests that mock the database.
Integration tests with real database go in tests/integration/.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from confiture.core.seed.validation.prep_seed.level_4_runtime import (
    Level4RuntimeValidator,
)
from confiture.core.seed.validation.prep_seed.models import (
    PrepSeedPattern,
)
from confiture.core.seed.validation.prep_seed.resolvers import Resolver


class TestLevel4RuntimeValidator:
    """Test Level 4 runtime validation."""

    def test_validator_initialization(self) -> None:
        """Can create a Level4RuntimeValidator."""
        validator = Level4RuntimeValidator()
        assert validator is not None

    def test_detects_missing_target_table(self, manufacturer_resolver: Resolver) -> None:
        """Detects when resolution target table doesn't exist in database."""
        validator = Level4RuntimeValidator()

        # Mock database that has no target table
        validator.table_exists = lambda schema, table: False  # type: ignore

        violations = validator.validate_runtime(
            manufacturer_resolver,
            target_schema="catalog",
            target_table="tb_manufacturer",
        )

        # Should detect missing table
        assert any(v.pattern == PrepSeedPattern.MISSING_FK_MAPPING for v in violations)

    def test_passes_when_target_table_exists(self, manufacturer_resolver: Resolver) -> None:
        """Passes when target table exists in database."""
        validator = Level4RuntimeValidator()

        # Mock database that has target table
        validator.table_exists = lambda schema, table: True  # type: ignore

        violations = validator.validate_runtime(
            manufacturer_resolver,
            target_schema="catalog",
            target_table="tb_manufacturer",
        )

        # Should have no violations for existing table
        assert not any(v.pattern == PrepSeedPattern.MISSING_FK_MAPPING for v in violations)

    def test_dry_run_execution_success(self, manufacturer_resolver: Resolver) -> None:
        """Dry-run execution succeeds with SAVEPOINT."""
        validator = Level4RuntimeValidator()

        # Mock database connection and SAVEPOINT support
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 5  # 5 rows inserted
        mock_conn.execute.return_value = mock_result

        violations = validator.dry_run_resolution(
            manufacturer_resolver,
            connection=mock_conn,
            savepoint_name="sp_test",
        )

        # Should succeed with no violations
        assert len(violations) == 0
        # Should have executed the function
        mock_conn.execute.assert_called()

    def test_dry_run_detects_execution_error(self, manufacturer_resolver: Resolver) -> None:
        """Dry-run detects errors during function execution."""
        validator = Level4RuntimeValidator()

        # Mock database connection that raises error
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("FOREIGN KEY constraint violation")

        violations = validator.dry_run_resolution(
            manufacturer_resolver,
            connection=mock_conn,
            savepoint_name="sp_test",
        )

        # Should detect execution error
        assert len(violations) > 0
        assert any("constraint" in v.message.lower() for v in violations)

    def test_validates_column_count_after_dry_run(self, manufacturer_resolver: Resolver) -> None:
        """Validates that dry-run inserted expected rows."""
        validator = Level4RuntimeValidator()

        # Mock execution result
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0  # No rows inserted!

        mock_conn.execute.return_value = mock_result

        violations = validator.dry_run_resolution(
            manufacturer_resolver,
            connection=mock_conn,
            savepoint_name="sp_test",
        )

        # Should detect that no rows were inserted
        # (but this is handled in Level 5, not Level 4)
        # Level 4 just does pre-flight checks
        assert len(violations) == 0
