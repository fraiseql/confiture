"""Tests for prep_seed violation models.

Cycle 1 & 2: Core Models - PrepSeedViolation, Report, and Pattern enum
"""

from __future__ import annotations

from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedReport,
    PrepSeedViolation,
    ViolationSeverity,
)


class TestPrepSeedPattern:
    """Test PrepSeedPattern enum."""

    def test_enum_has_schema_drift_pattern(self) -> None:
        """Schema drift is a pattern we can detect."""
        assert hasattr(PrepSeedPattern, "SCHEMA_DRIFT_IN_RESOLVER")

    def test_enum_has_missing_fk_transformation(self) -> None:
        """Missing FK transformation is a pattern we detect."""
        assert hasattr(PrepSeedPattern, "MISSING_FK_TRANSFORMATION")

    def test_pattern_has_description(self) -> None:
        """Each pattern has a human-readable description."""
        pattern = PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER
        assert isinstance(pattern.description, str)
        assert len(pattern.description) > 0

    def test_pattern_has_fix_available_flag(self) -> None:
        """Some patterns are auto-fixable."""
        assert hasattr(PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER, "fix_available")
        assert isinstance(PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER.fix_available, bool)


class TestViolationSeverity:
    """Test ViolationSeverity enum."""

    def test_severity_levels_exist(self) -> None:
        """Severity levels for categorizing violations."""
        assert hasattr(ViolationSeverity, "INFO")
        assert hasattr(ViolationSeverity, "WARNING")
        assert hasattr(ViolationSeverity, "ERROR")
        assert hasattr(ViolationSeverity, "CRITICAL")


class TestPrepSeedViolation:
    """Test PrepSeedViolation dataclass."""

    def test_violation_creation(self) -> None:
        """Can create a violation with required fields."""
        violation = PrepSeedViolation(
            pattern=PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER,
            severity=ViolationSeverity.CRITICAL,
            message="Function references tenant.tb_manufacturer but table is in catalog.tb_manufacturer",
            file_path="db/schema/fn_resolve_manufacturer.sql",
            line_number=15,
        )

        assert violation.pattern == PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER
        assert violation.severity == ViolationSeverity.CRITICAL
        assert "tenant.tb_manufacturer" in violation.message
        assert violation.file_path == "db/schema/fn_resolve_manufacturer.sql"
        assert violation.line_number == 15

    def test_violation_optional_fields(self) -> None:
        """Can add optional fields to violation."""
        violation = PrepSeedViolation(
            pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
            severity=ViolationSeverity.ERROR,
            message="Missing JOIN for FK transformation",
            file_path="db/schema/functions.sql",
            line_number=10,
            impact="15 dependent tables will have NULL foreign keys",
            fix_available=True,
            suggestion="Add: LEFT JOIN catalog.tb_manufacturer m ON m.id = p.fk_manufacturer_id",
        )

        assert violation.impact is not None
        assert violation.fix_available is True
        assert violation.suggestion is not None

    def test_violation_to_dict(self) -> None:
        """Violation can be serialized to dictionary."""
        violation = PrepSeedViolation(
            pattern=PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER,
            severity=ViolationSeverity.CRITICAL,
            message="Schema mismatch detected",
            file_path="test.sql",
            line_number=5,
        )

        result = violation.to_dict()
        assert result["pattern"] == "SCHEMA_DRIFT_IN_RESOLVER"
        assert result["severity"] == "CRITICAL"
        assert result["message"] == "Schema mismatch detected"
        assert result["file_path"] == "test.sql"
        assert result["line_number"] == 5


class TestPrepSeedReport:
    """Test PrepSeedReport dataclass."""

    def test_empty_report(self) -> None:
        """Can create empty report."""
        report = PrepSeedReport()

        assert report.violations == []
        assert report.scanned_files == []
        assert not report.has_violations
        assert report.violation_count == 0

    def test_add_violation(self) -> None:
        """Can add violations to report."""
        report = PrepSeedReport()
        violation = PrepSeedViolation(
            pattern=PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER,
            severity=ViolationSeverity.CRITICAL,
            message="Test",
            file_path="test.sql",
            line_number=1,
        )

        report.add_violation(violation)

        assert report.violation_count == 1
        assert report.has_violations is True
        assert report.violations[0] == violation

    def test_add_scanned_file(self) -> None:
        """Can record scanned files."""
        report = PrepSeedReport()

        report.add_file_scanned("functions.sql")
        report.add_file_scanned("seeds.sql")

        assert len(report.scanned_files) == 2
        assert "functions.sql" in report.scanned_files

    def test_report_grouping_by_severity(self) -> None:
        """Can group violations by severity level."""
        report = PrepSeedReport()

        v1 = PrepSeedViolation(
            pattern=PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER,
            severity=ViolationSeverity.CRITICAL,
            message="Critical issue",
            file_path="test.sql",
            line_number=1,
        )
        v2 = PrepSeedViolation(
            pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
            severity=ViolationSeverity.WARNING,
            message="Warning",
            file_path="test.sql",
            line_number=5,
        )

        report.add_violation(v1)
        report.add_violation(v2)

        by_severity = report.violations_by_severity()
        assert len(by_severity[ViolationSeverity.CRITICAL]) == 1
        assert len(by_severity[ViolationSeverity.WARNING]) == 1

    def test_report_to_dict(self) -> None:
        """Report can be serialized to dictionary."""
        report = PrepSeedReport()
        report.add_file_scanned("test.sql")
        report.add_violation(
            PrepSeedViolation(
                pattern=PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER,
                severity=ViolationSeverity.CRITICAL,
                message="Test",
                file_path="test.sql",
                line_number=1,
            )
        )

        result = report.to_dict()
        assert result["violation_count"] == 1
        assert result["has_violations"] is True
        assert len(result["violations"]) == 1
