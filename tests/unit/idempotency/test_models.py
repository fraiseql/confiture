"""Tests for idempotency validation models."""

from confiture.core.idempotency.models import (
    IdempotencyPattern,
    IdempotencyReport,
    IdempotencyViolation,
)


class TestIdempotencyViolation:
    """Tests for IdempotencyViolation dataclass."""

    def test_create_violation_with_required_fields(self):
        """Violation can be created with pattern, location, and line number."""
        violation = IdempotencyViolation(
            pattern=IdempotencyPattern.CREATE_TABLE,
            sql_snippet="CREATE TABLE users",
            line_number=15,
            file_path="db/migrations/001_init.up.sql",
        )

        assert violation.pattern == IdempotencyPattern.CREATE_TABLE
        assert violation.sql_snippet == "CREATE TABLE users"
        assert violation.line_number == 15
        assert violation.file_path == "db/migrations/001_init.up.sql"

    def test_violation_has_suggestion(self):
        """Violation includes suggestion for making it idempotent."""
        violation = IdempotencyViolation(
            pattern=IdempotencyPattern.CREATE_TABLE,
            sql_snippet="CREATE TABLE users",
            line_number=15,
            file_path="db/migrations/001_init.up.sql",
        )

        assert violation.suggestion is not None
        assert "IF NOT EXISTS" in violation.suggestion

    def test_violation_has_fix_available_flag(self):
        """Violation indicates whether auto-fix is available."""
        violation = IdempotencyViolation(
            pattern=IdempotencyPattern.CREATE_TABLE,
            sql_snippet="CREATE TABLE users",
            line_number=15,
            file_path="db/migrations/001_init.up.sql",
        )

        assert violation.fix_available is True

    def test_violation_str_formatting(self):
        """Violation has human-readable string representation."""
        violation = IdempotencyViolation(
            pattern=IdempotencyPattern.CREATE_INDEX,
            sql_snippet="CREATE INDEX idx_users_email ON users(email)",
            line_number=42,
            file_path="db/migrations/002_indexes.up.sql",
        )

        str_repr = str(violation)
        assert "002_indexes.up.sql" in str_repr
        assert "42" in str_repr
        assert "CREATE INDEX" in str_repr


class TestIdempotencyPattern:
    """Tests for IdempotencyPattern enum."""

    def test_all_patterns_have_suggestions(self):
        """Every pattern has a corresponding suggestion."""
        for pattern in IdempotencyPattern:
            assert pattern.suggestion is not None
            assert len(pattern.suggestion) > 0

    def test_all_patterns_have_fix_available_flag(self):
        """Every pattern indicates if auto-fix is available."""
        for pattern in IdempotencyPattern:
            assert isinstance(pattern.fix_available, bool)


class TestIdempotencyReport:
    """Tests for IdempotencyReport dataclass."""

    def test_empty_report(self):
        """Empty report has no violations."""
        report = IdempotencyReport()

        assert report.violations == []
        assert report.has_violations is False
        assert report.violation_count == 0

    def test_add_violation(self):
        """Can add violations to report."""
        report = IdempotencyReport()
        violation = IdempotencyViolation(
            pattern=IdempotencyPattern.CREATE_TABLE,
            sql_snippet="CREATE TABLE users",
            line_number=15,
            file_path="001_init.up.sql",
        )

        report.add_violation(violation)

        assert report.has_violations is True
        assert report.violation_count == 1
        assert violation in report.violations

    def test_report_tracks_files_scanned(self):
        """Report tracks which files were scanned."""
        report = IdempotencyReport()
        report.add_file_scanned("001_init.up.sql")
        report.add_file_scanned("002_add_users.up.sql")

        assert report.files_scanned == 2
        assert "001_init.up.sql" in report.scanned_files

    def test_report_to_dict(self):
        """Report can be serialized to dictionary."""
        report = IdempotencyReport()
        violation = IdempotencyViolation(
            pattern=IdempotencyPattern.CREATE_TABLE,
            sql_snippet="CREATE TABLE users",
            line_number=15,
            file_path="001_init.up.sql",
        )
        report.add_violation(violation)
        report.add_file_scanned("001_init.up.sql")

        data = report.to_dict()

        assert "violations" in data
        assert "files_scanned" in data
        assert "violation_count" in data
        assert len(data["violations"]) == 1

    def test_report_violations_by_file(self):
        """Report can group violations by file."""
        report = IdempotencyReport()
        report.add_violation(
            IdempotencyViolation(
                pattern=IdempotencyPattern.CREATE_TABLE,
                sql_snippet="CREATE TABLE a",
                line_number=1,
                file_path="001_init.up.sql",
            )
        )
        report.add_violation(
            IdempotencyViolation(
                pattern=IdempotencyPattern.CREATE_INDEX,
                sql_snippet="CREATE INDEX idx",
                line_number=10,
                file_path="001_init.up.sql",
            )
        )
        report.add_violation(
            IdempotencyViolation(
                pattern=IdempotencyPattern.CREATE_TABLE,
                sql_snippet="CREATE TABLE b",
                line_number=5,
                file_path="002_more.up.sql",
            )
        )

        by_file = report.violations_by_file()

        assert len(by_file["001_init.up.sql"]) == 2
        assert len(by_file["002_more.up.sql"]) == 1


class TestSeverityField:
    def test_default_severity_is_error(self):
        from confiture.core.idempotency.models import (
            IdempotencyPattern,
            IdempotencyViolation,
        )

        v = IdempotencyViolation(
            pattern=IdempotencyPattern.CREATE_TABLE,
            sql_snippet="CREATE TABLE foo",
            line_number=1,
            file_path="x.sql",
        )
        assert v.severity == "error"

    def test_severity_roundtrips_through_to_dict(self):
        from confiture.core.idempotency.models import (
            IdempotencyPattern,
            IdempotencyViolation,
        )

        info_v = IdempotencyViolation(
            pattern=IdempotencyPattern.CREATE_TABLE,
            sql_snippet="CREATE TABLE foo",
            line_number=1,
            file_path="x.sql",
            severity="info",
        )
        d = info_v.to_dict()
        assert d["severity"] == "info"

        # Error-severity also emitted explicitly (no ambiguity).
        err_v = IdempotencyViolation(
            pattern=IdempotencyPattern.CREATE_TABLE,
            sql_snippet="CREATE TABLE foo",
            line_number=1,
            file_path="x.sql",
        )
        assert err_v.to_dict()["severity"] == "error"

    def test_has_blocking_violations_only_counts_errors(self):
        from confiture.core.idempotency.models import (
            IdempotencyPattern,
            IdempotencyReport,
            IdempotencyViolation,
        )

        report = IdempotencyReport()
        report.add_violation(
            IdempotencyViolation(
                pattern=IdempotencyPattern.CREATE_VIEW,
                sql_snippet="x",
                line_number=1,
                file_path="x.sql",
                severity="info",
            )
        )
        assert report.has_violations is True
        assert report.has_blocking_violations is False

        report.add_violation(
            IdempotencyViolation(
                pattern=IdempotencyPattern.CREATE_TABLE,
                sql_snippet="y",
                line_number=2,
                file_path="x.sql",
            )
        )
        assert report.has_blocking_violations is True

    def test_report_to_dict_includes_has_blocking_violations(self):
        from confiture.core.idempotency.models import IdempotencyReport

        d = IdempotencyReport().to_dict()
        assert d["has_blocking_violations"] is False
