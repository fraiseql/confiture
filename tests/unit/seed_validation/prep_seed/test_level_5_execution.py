"""Tests for Level 5 - Full seed execution.

Cycles 5-8: Seed loading, resolution execution, NULL FK detection, data integrity.

Note: These are unit tests that mock the database.
Integration tests with real database go in tests/integration/.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import psycopg
import pytest

from confiture.core import live_catalog
from confiture.core.schema_model import Column
from confiture.core.seed.validation.prep_seed.level_5_execution import (
    Level5ExecutionValidator,
)
from confiture.core.seed.validation.prep_seed.models import (
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
        mock_conn.execute.side_effect = psycopg.ProgrammingError("Syntax error in seed file")

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

    # The columns come from `live_catalog.columns`; what is tested here is which
    # of them level 5 counts NULLs in. The counts themselves are measured on a
    # real database in tests/integration/test_level_5_measures_data.py.

    @staticmethod
    def _columns(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
        monkeypatch.setattr(
            live_catalog,
            "columns",
            lambda *_a, **_k: tuple(Column(name=n, folded=n, line=0) for n in names),
        )

    def test_detects_null_fks_after_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Detects NULL foreign keys after resolution."""
        validator = Level5ExecutionValidator()
        self._columns(monkeypatch, "pk_product", "fk_manufacturer", "fk_category")

        # Mock database with NULL FKs: every count comes back 1
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (1,)

        violations = validator.detect_null_fks(
            connection=mock_conn,
            tables=["tb_product", "tb_category"],
        )

        # Should detect NULL FKs, in the fk_ columns only
        assert any(v.pattern == PrepSeedPattern.NULL_FK_AFTER_RESOLUTION for v in violations)
        assert not any("pk_product" in v.message for v in violations)

        # Should describe impact
        null_violation = next(
            v for v in violations if v.pattern == PrepSeedPattern.NULL_FK_AFTER_RESOLUTION
        )
        assert "tb_product" in null_violation.message
        assert null_violation.severity == ViolationSeverity.CRITICAL

    def test_passes_when_no_null_fks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Passes when all FK values are non-NULL."""
        validator = Level5ExecutionValidator()
        self._columns(monkeypatch, "fk_manufacturer")

        # Mock database with no NULL FKs
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (0,)

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


# The tests that used to sit here — `test_full_execution_cycle` and the whole
# `TestLevel5ConstraintValidation` class — mocked `fetchall()` with the rows they
# wanted back and pinned `execute.side_effect` to the exact sequence of calls.
# They asserted that a violation list built from hand-fed rows was non-empty,
# which is true whatever SQL produced those rows, and four of the five queries
# produced none of them: they counted `information_schema` entries and reported
# the count as a number of violating rows. See
# `tests/integration/test_level_5_measures_data.py`, which asks a real database
# instead and is the only place that could have failed on this.
