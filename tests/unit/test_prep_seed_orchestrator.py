"""Tests for PrepSeedOrchestrator.

Tests the orchestration of all 5 validation levels with progressive execution,
violation accumulation, and early exit on CRITICAL violations.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.core.seed_validation.prep_seed import (
    PrepSeedReport,
    PrepSeedViolation,
    ViolationSeverity,
)
from confiture.core.seed_validation.prep_seed.models import PrepSeedPattern
from confiture.core.seed_validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)


class TestOrchestrationConfig:
    """Test OrchestrationConfig dataclass."""

    def test_config_creation_minimal(self) -> None:
        """Test creating config with minimal parameters."""
        config = OrchestrationConfig(
            max_level=3,
            seeds_dir=Path("db/seeds/prep"),
            schema_dir=Path("db/schema"),
        )
        assert config.max_level == 3
        assert config.seeds_dir == Path("db/seeds/prep")
        assert config.schema_dir == Path("db/schema")
        assert config.database_url is None
        assert config.stop_on_critical is True
        assert config.show_progress is True

    def test_config_creation_full(self) -> None:
        """Test creating config with all parameters."""
        config = OrchestrationConfig(
            max_level=5,
            seeds_dir=Path("db/seeds/prep"),
            schema_dir=Path("db/schema"),
            database_url="postgresql://localhost/test",
            stop_on_critical=False,
            show_progress=False,
        )
        assert config.max_level == 5
        assert config.database_url == "postgresql://localhost/test"
        assert config.stop_on_critical is False
        assert config.show_progress is False


class TestPrepSeedOrchestrator:
    """Test PrepSeedOrchestrator orchestration."""

    def test_orchestrator_init(self) -> None:
        """Test orchestrator initialization."""
        config = OrchestrationConfig(
            max_level=3,
            seeds_dir=Path("db/seeds/prep"),
            schema_dir=Path("db/schema"),
        )
        orchestrator = PrepSeedOrchestrator(config)
        assert orchestrator.config == config

    def test_run_level_1_only(self, tmp_path: Path) -> None:
        """Test running only Level 1 validation."""
        # Create temp seed file
        seeds_dir = tmp_path / "db" / "seeds" / "prep"
        seeds_dir.mkdir(parents=True)
        test_file = seeds_dir / "test.sql"
        test_file.write_text("INSERT INTO catalog.tb_x VALUES (1);")

        config = OrchestrationConfig(
            max_level=1,
            seeds_dir=seeds_dir,
            schema_dir=tmp_path / "db" / "schema",
        )
        orchestrator = PrepSeedOrchestrator(config)

        # Mock Level 1 validator
        mock_violation = PrepSeedViolation(
            pattern=PrepSeedPattern.PREP_SEED_TARGET_MISMATCH,
            severity=ViolationSeverity.ERROR,
            message="Test violation",
            file_path=str(test_file),
            line_number=1,
        )

        with patch(
            "confiture.core.seed_validation.prep_seed.orchestrator.Level1SeedValidator"
        ) as mock_level1:
            mock_instance = MagicMock()
            mock_instance.validate_seed_file.return_value = [mock_violation]
            mock_level1.return_value = mock_instance

            report = orchestrator.run()

        assert isinstance(report, PrepSeedReport)
        assert len(report.violations) == 1
        assert report.violations[0].pattern == PrepSeedPattern.PREP_SEED_TARGET_MISMATCH

    def test_run_levels_1_through_3(self, tmp_path: Path) -> None:
        """Test running Levels 1-3 (static validation)."""
        # Create empty temp directories
        seeds_dir = tmp_path / "db" / "seeds" / "prep"
        seeds_dir.mkdir(parents=True)
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        config = OrchestrationConfig(
            max_level=3,
            seeds_dir=seeds_dir,
            schema_dir=schema_dir,
        )
        orchestrator = PrepSeedOrchestrator(config)

        # Mock validators to return no violations
        with (
            patch(
                "confiture.core.seed_validation.prep_seed.orchestrator.Level1SeedValidator"
            ) as mock_level1,
            patch(
                "confiture.core.seed_validation.prep_seed.orchestrator.Level3ResolutionValidator"
            ) as mock_level3,
        ):
            l1 = MagicMock()
            l1.validate_seed_file.return_value = []
            mock_level1.return_value = l1

            l3 = MagicMock()
            l3.validate_function.return_value = []
            mock_level3.return_value = l3

            report = orchestrator.run()

        assert isinstance(report, PrepSeedReport)
        assert report.violation_count == 0

    def test_early_exit_on_critical_violation(self, tmp_path: Path) -> None:
        """Test that orchestrator stops at CRITICAL violation when configured."""
        # Create temp directories and files
        seeds_dir = tmp_path / "db" / "seeds" / "prep"
        seeds_dir.mkdir(parents=True)
        (seeds_dir / "test.sql").write_text("INSERT INTO prep_seed.tb_x VALUES (1);")

        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "table.sql").write_text("CREATE TABLE tb_x (id BIGINT);")
        (schema_dir / "fn_resolve_x.sql").write_text("CREATE FUNCTION fn_resolve_x() AS $$$$;")

        config = OrchestrationConfig(
            max_level=3,  # Use level 3 (no database required)
            seeds_dir=seeds_dir,
            schema_dir=schema_dir,
            stop_on_critical=True,
        )
        orchestrator = PrepSeedOrchestrator(config)

        # Mock Level 3 to return CRITICAL violation
        critical_violation = PrepSeedViolation(
            pattern=PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER,
            severity=ViolationSeverity.CRITICAL,
            message="Schema drift detected",
            file_path="db/schema/functions/fn_resolve.sql",
            line_number=5,
        )

        with (
            patch(
                "confiture.core.seed_validation.prep_seed.orchestrator.Level1SeedValidator"
            ) as mock_level1,
            patch(
                "confiture.core.seed_validation.prep_seed.orchestrator.Level3ResolutionValidator"
            ) as mock_level3,
        ):
            # Set up mocks
            l1 = MagicMock()
            l1.validate_seed_file.return_value = []
            mock_level1.return_value = l1

            l3 = MagicMock()
            l3.validate_function.return_value = [critical_violation]
            mock_level3.return_value = l3

            report = orchestrator.run()

        # Should have critical violation and stop there
        assert len(report.violations) == 1
        assert report.violations[0].severity == ViolationSeverity.CRITICAL

    def test_continue_on_critical_when_disabled(self, tmp_path: Path) -> None:
        """Test that orchestrator continues past CRITICAL if stop_on_critical=False."""
        # Create temp directories and files
        seeds_dir = tmp_path / "db" / "seeds" / "prep"
        seeds_dir.mkdir(parents=True)
        (seeds_dir / "test.sql").write_text("INSERT INTO prep_seed.tb_x VALUES (1);")

        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "table.sql").write_text("CREATE TABLE tb_x (id BIGINT);")
        (schema_dir / "fn_resolve_x.sql").write_text("CREATE FUNCTION fn_resolve_x() AS $$$$;")

        config = OrchestrationConfig(
            max_level=3,  # Use level 3 (no database required)
            seeds_dir=seeds_dir,
            schema_dir=schema_dir,
            stop_on_critical=False,
        )
        orchestrator = PrepSeedOrchestrator(config)

        critical_violation = PrepSeedViolation(
            pattern=PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER,
            severity=ViolationSeverity.CRITICAL,
            message="Schema drift detected",
            file_path="db/schema/functions/fn_resolve.sql",
            line_number=5,
        )

        with (
            patch(
                "confiture.core.seed_validation.prep_seed.orchestrator.Level1SeedValidator"
            ) as mock_level1,
            patch(
                "confiture.core.seed_validation.prep_seed.orchestrator.Level3ResolutionValidator"
            ) as mock_level3,
        ):
            l1 = MagicMock()
            l1.validate_seed_file.return_value = []
            mock_level1.return_value = l1

            # Level 3 returns CRITICAL
            l3 = MagicMock()
            l3.validate_function.return_value = [critical_violation]
            mock_level3.return_value = l3

            report = orchestrator.run()

        # Should have critical violation and continue to next level
        assert len(report.violations) >= 1
        assert report.violations[0].severity == ViolationSeverity.CRITICAL

    def test_accumulate_violations_across_levels(self, tmp_path: Path) -> None:
        """Test that violations are accumulated from all levels."""
        # Create temp directories and files
        seeds_dir = tmp_path / "db" / "seeds" / "prep"
        seeds_dir.mkdir(parents=True)
        (seeds_dir / "test.sql").write_text("INSERT INTO prep_seed.tb_x VALUES (1);")

        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "table.sql").write_text("CREATE TABLE tb_x (id BIGINT);")
        (schema_dir / "fn_resolve_x.sql").write_text(
            "CREATE FUNCTION fn_resolve_x() AS $$$$;"
        )

        config = OrchestrationConfig(
            max_level=3,
            seeds_dir=seeds_dir,
            schema_dir=schema_dir,
        )
        orchestrator = PrepSeedOrchestrator(config)

        violation1 = PrepSeedViolation(
            pattern=PrepSeedPattern.PREP_SEED_TARGET_MISMATCH,
            severity=ViolationSeverity.ERROR,
            message="Level 1 violation",
            file_path="db/seeds/prep/test.sql",
            line_number=1,
        )

        violation3 = PrepSeedViolation(
            pattern=PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER,
            severity=ViolationSeverity.CRITICAL,
            message="Level 3 violation",
            file_path="db/schema/fn_resolve.sql",
            line_number=5,
        )

        with (
            patch(
                "confiture.core.seed_validation.prep_seed.orchestrator.Level1SeedValidator"
            ) as mock_level1,
            patch(
                "confiture.core.seed_validation.prep_seed.orchestrator.Level3ResolutionValidator"
            ) as mock_level3,
        ):
            l1 = MagicMock()
            l1.validate_seed_file.return_value = [violation1]
            mock_level1.return_value = l1

            l3 = MagicMock()
            l3.validate_function.return_value = [violation3]
            mock_level3.return_value = l3

            report = orchestrator.run()

        # Should accumulate from Level 1 and Level 3
        assert len(report.violations) == 2
        violations_by_pattern = {v.pattern: v for v in report.violations}
        assert PrepSeedPattern.PREP_SEED_TARGET_MISMATCH in violations_by_pattern
        assert PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER in violations_by_pattern

    def test_database_url_required_for_level_4(self) -> None:
        """Test that database_url is required for level 4+."""
        config = OrchestrationConfig(
            max_level=4,
            seeds_dir=Path("db/seeds/prep"),
            schema_dir=Path("db/schema"),
            database_url=None,  # Missing database URL
        )
        orchestrator = PrepSeedOrchestrator(config)

        with pytest.raises(ValueError, match="database_url.*required.*level"):
            orchestrator.run()

    def test_report_includes_scanned_files(self) -> None:
        """Test that report includes list of scanned files."""
        config = OrchestrationConfig(
            max_level=1,
            seeds_dir=Path("db/seeds/prep"),
            schema_dir=Path("db/schema"),
        )
        orchestrator = PrepSeedOrchestrator(config)

        with (
            patch(
                "confiture.core.seed_validation.prep_seed.orchestrator.Level1SeedValidator"
            ) as mock_level1,
            patch("confiture.core.seed_validation.prep_seed.orchestrator.Path.rglob") as mock_rglob,
        ):
            test_file = Path("db/seeds/prep/test.sql")
            mock_rglob.return_value = [test_file]

            l1 = MagicMock()
            l1.validate_seed_file.return_value = []
            mock_level1.return_value = l1

            report = orchestrator.run()

        assert "db/seeds/prep/test.sql" in report.scanned_files
