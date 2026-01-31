"""Orchestrator for 5-level prep-seed validation with progressive execution.

This module coordinates running all validation levels (1-5) sequentially,
accumulating violations, and optionally stopping early on CRITICAL violations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from confiture.core.seed_validation.prep_seed.level_1_seed_files import (
    Level1SeedValidator,
)
from confiture.core.seed_validation.prep_seed.level_3_resolvers import (
    Level3ResolutionValidator,
)
from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedReport,
    PrepSeedViolation,
    ViolationSeverity,
)


@dataclass
class OrchestrationConfig:
    """Configuration for orchestrating prep-seed validation.

    Attributes:
        max_level: Maximum validation level to run (1-5)
        seeds_dir: Directory containing seed files
        schema_dir: Directory containing schema files
        database_url: Optional database URL for levels 4-5
        stop_on_critical: Stop early if CRITICAL violation found (default: True)
        show_progress: Show progress indicators during validation (default: True)
    """

    max_level: int
    seeds_dir: Path
    schema_dir: Path
    database_url: str | None = None
    stop_on_critical: bool = True
    show_progress: bool = True


class PrepSeedOrchestrator:
    """Orchestrates 5-level prep-seed validation with progressive execution.

    Runs validators 1→N sequentially, accumulates violations across levels,
    and optionally stops early on CRITICAL violations.

    Example:
        >>> config = OrchestrationConfig(
        ...     max_level=3,
        ...     seeds_dir=Path("db/seeds/prep"),
        ...     schema_dir=Path("db/schema"),
        ... )
        >>> orchestrator = PrepSeedOrchestrator(config)
        >>> report = orchestrator.run()
        >>> if report.has_violations:
        ...     print(f"Found {report.violation_count} violations")
    """

    def __init__(self, config: OrchestrationConfig) -> None:
        """Initialize orchestrator.

        Args:
            config: Orchestration configuration
        """
        self.config = config

    def run(self) -> PrepSeedReport:
        """Run validation levels 1 through max_level.

        Runs validators sequentially, accumulating violations. Stops early on
        CRITICAL violations if configured.

        Returns:
            PrepSeedReport with accumulated violations from all levels

        Raises:
            ValueError: If database_url required for max_level but not provided
        """
        # Validate prerequisites
        if self.config.max_level >= 4 and not self.config.database_url:
            msg = "database_url required for levels 4-5"
            raise ValueError(msg)

        # Initialize report
        report = PrepSeedReport()

        # Level 1: Seed file validation
        if self.config.max_level >= 1:
            violations = self._run_level_1()
            report.violations.extend(violations)
            self._record_scanned_files_level1(report)

            if self._should_exit_early(report):
                return report

        # Level 2: Schema consistency
        if self.config.max_level >= 2:
            violations = self._run_level_2()
            report.violations.extend(violations)

            if self._should_exit_early(report):
                return report

        # Level 3: Resolution function validation (CRITICAL level)
        if self.config.max_level >= 3:
            violations = self._run_level_3()
            report.violations.extend(violations)

            if self._should_exit_early(report):
                return report

        # Level 4: Runtime validation
        if self.config.max_level >= 4:
            violations = self._run_level_4()
            report.violations.extend(violations)

            if self._should_exit_early(report):
                return report

        # Level 5: Full execution
        if self.config.max_level >= 5:
            violations = self._run_level_5()
            report.violations.extend(violations)

        return report

    def _run_level_1(self) -> list[PrepSeedViolation]:
        """Run Level 1: Seed file validation."""
        validator = Level1SeedValidator()
        violations: list[PrepSeedViolation] = []

        # Scan for seed files
        sql_files = list(self.config.seeds_dir.rglob("*.sql"))

        for file_path in sql_files:
            try:
                content = file_path.read_text()
                file_violations = validator.validate_seed_file(content, str(file_path))
                violations.extend(file_violations)
            except OSError:
                # Skip files that can't be read
                pass

        return violations

    def _run_level_2(self) -> list[PrepSeedViolation]:
        """Run Level 2: Schema consistency validation."""
        # Level 2 validates schema mappings, which requires analyzing
        # schema files for table definitions. For now, return empty.
        # Full implementation would require parsing schema DDL.
        return []

    def _run_level_3(self) -> list[PrepSeedViolation]:
        """Run Level 3: Resolution function validation."""
        validator = Level3ResolutionValidator()
        violations: list[PrepSeedViolation] = []

        # Find resolution functions
        func_files = list(self.config.schema_dir.rglob("fn_resolve*.sql"))

        for file_path in func_files:
            try:
                content = file_path.read_text()
                func_name = file_path.stem
                file_violations = validator.validate_function(func_name, content)
                violations.extend(file_violations)
            except OSError:
                pass

        return violations

    def _run_level_4(self) -> list[PrepSeedViolation]:
        """Run Level 4: Runtime validation."""
        # Level 4 requires database connection for dry-run validation.
        # Would use Level4RuntimeValidator with actual database here.
        return []

    def _run_level_5(self) -> list[PrepSeedViolation]:
        """Run Level 5: Full execution validation."""
        # Level 5 requires database connection for full seed execution.
        # Would use Level5ExecutionValidator with actual database here.
        return []

    def _should_exit_early(self, report: PrepSeedReport) -> bool:
        """Check if orchestrator should exit early.

        Early exit occurs when:
        1. stop_on_critical is True AND
        2. Report contains at least one CRITICAL violation

        Args:
            report: Current report to check

        Returns:
            True if should exit early, False otherwise
        """
        if not self.config.stop_on_critical:
            return False

        return any(v.severity == ViolationSeverity.CRITICAL for v in report.violations)

    def _record_scanned_files_level1(self, report: PrepSeedReport) -> None:
        """Record scanned files from Level 1 to report."""
        sql_files = list(self.config.seeds_dir.rglob("*.sql"))
        for file_path in sql_files:
            report.add_file_scanned(str(file_path))
