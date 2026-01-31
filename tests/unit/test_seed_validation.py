"""Unit tests for seed validation module.

Tests for data models, pattern detection, and validation logic.
"""

from __future__ import annotations

from confiture.core.seed_validation.models import (
    SeedValidationPattern,
    SeedValidationReport,
    SeedViolation,
)


class TestSeedValidationPattern:
    """Test SeedValidationPattern enum."""

    def test_enum_members_exist(self) -> None:
        """Test that required pattern enum members exist."""
        assert hasattr(SeedValidationPattern, "DOUBLE_SEMICOLON")
        assert hasattr(SeedValidationPattern, "NON_INSERT_STATEMENT")
        assert hasattr(SeedValidationPattern, "MISSING_ON_CONFLICT")
        assert hasattr(SeedValidationPattern, "INVALID_UUID_FORMAT")
        assert hasattr(SeedValidationPattern, "COLUMN_VALUE_MISMATCH")

    def test_pattern_suggestion_available(self) -> None:
        """Test that patterns have suggestions."""
        pattern = SeedValidationPattern.DOUBLE_SEMICOLON
        assert hasattr(pattern, "suggestion")
        assert isinstance(pattern.suggestion, str)
        assert len(pattern.suggestion) > 0

    def test_pattern_fix_available_property(self) -> None:
        """Test that patterns have fix_available property."""
        pattern = SeedValidationPattern.MISSING_ON_CONFLICT
        assert hasattr(pattern, "fix_available")
        assert isinstance(pattern.fix_available, bool)

    def test_missing_on_conflict_is_fixable(self) -> None:
        """Test that MISSING_ON_CONFLICT is marked as fixable."""
        assert SeedValidationPattern.MISSING_ON_CONFLICT.fix_available is True

    def test_double_semicolon_not_fixable(self) -> None:
        """Test that DOUBLE_SEMICOLON is not fixable."""
        assert SeedValidationPattern.DOUBLE_SEMICOLON.fix_available is False


class TestSeedViolation:
    """Test SeedViolation dataclass."""

    def test_create_violation(self) -> None:
        """Test creating a seed violation."""
        violation = SeedViolation(
            pattern=SeedValidationPattern.DOUBLE_SEMICOLON,
            sql_snippet="INSERT INTO users VALUES (1, 'test');;",
            line_number=5,
            file_path="db/seeds/test/data.sql",
        )
        assert violation.pattern == SeedValidationPattern.DOUBLE_SEMICOLON
        assert violation.line_number == 5
        assert violation.file_path == "db/seeds/test/data.sql"

    def test_violation_suggestion(self) -> None:
        """Test that violation returns suggestion from pattern."""
        violation = SeedViolation(
            pattern=SeedValidationPattern.MISSING_ON_CONFLICT,
            sql_snippet="INSERT INTO users (id, name) VALUES (1, 'test');",
            line_number=1,
            file_path="seeds.sql",
        )
        assert violation.suggestion == SeedValidationPattern.MISSING_ON_CONFLICT.suggestion

    def test_violation_fix_available(self) -> None:
        """Test that violation exposes fix_available from pattern."""
        violation = SeedViolation(
            pattern=SeedValidationPattern.MISSING_ON_CONFLICT,
            sql_snippet="INSERT INTO users (id) VALUES (1);",
            line_number=1,
            file_path="seeds.sql",
        )
        assert violation.fix_available is True

    def test_violation_str_short_snippet(self) -> None:
        """Test string representation with short snippet."""
        violation = SeedViolation(
            pattern=SeedValidationPattern.DOUBLE_SEMICOLON,
            sql_snippet="INSERT INTO users VALUES (1);",
            line_number=5,
            file_path="data.sql",
        )
        str_repr = str(violation)
        assert "data.sql:5" in str_repr
        assert "DOUBLE_SEMICOLON" in str_repr

    def test_violation_str_long_snippet(self) -> None:
        """Test string representation truncates long snippets."""
        long_snippet = "INSERT INTO users (id, name, email, phone) VALUES (1, 'test', 'test@example.com', '555-1234');"
        violation = SeedViolation(
            pattern=SeedValidationPattern.MISSING_ON_CONFLICT,
            sql_snippet=long_snippet,
            line_number=10,
            file_path="seeds.sql",
        )
        str_repr = str(violation)
        assert "seeds.sql:10" in str_repr
        assert "..." in str_repr  # Should be truncated

    def test_violation_to_dict(self) -> None:
        """Test violation serialization to dictionary."""
        violation = SeedViolation(
            pattern=SeedValidationPattern.DOUBLE_SEMICOLON,
            sql_snippet="INSERT INTO users VALUES (1);;",
            line_number=3,
            file_path="seeds.sql",
        )
        data = violation.to_dict()
        assert data["pattern"] == "DOUBLE_SEMICOLON"
        assert data["line_number"] == 3
        assert data["file_path"] == "seeds.sql"
        assert "suggestion" in data
        assert "fix_available" in data


class TestSeedValidationReport:
    """Test SeedValidationReport class."""

    def test_create_empty_report(self) -> None:
        """Test creating an empty report."""
        report = SeedValidationReport()
        assert report.violation_count == 0
        assert not report.has_violations
        assert report.files_scanned == 0

    def test_add_violation(self) -> None:
        """Test adding a violation to report."""
        report = SeedValidationReport()
        violation = SeedViolation(
            pattern=SeedValidationPattern.DOUBLE_SEMICOLON,
            sql_snippet="INSERT INTO users VALUES (1);;",
            line_number=1,
            file_path="seeds.sql",
        )
        report.add_violation(violation)
        assert report.violation_count == 1
        assert report.has_violations

    def test_add_file_scanned(self) -> None:
        """Test adding scanned file to report."""
        report = SeedValidationReport()
        report.add_file_scanned("db/seeds/001_users.sql")
        assert report.files_scanned == 1
        assert "db/seeds/001_users.sql" in report.scanned_files

    def test_add_file_scanned_no_duplicates(self) -> None:
        """Test that same file is not added twice."""
        report = SeedValidationReport()
        report.add_file_scanned("seeds.sql")
        report.add_file_scanned("seeds.sql")
        assert report.files_scanned == 1

    def test_violations_by_file(self) -> None:
        """Test grouping violations by file."""
        report = SeedValidationReport()
        v1 = SeedViolation(
            pattern=SeedValidationPattern.DOUBLE_SEMICOLON,
            sql_snippet="INSERT VALUES (1);;",
            line_number=1,
            file_path="seeds_a.sql",
        )
        v2 = SeedViolation(
            pattern=SeedValidationPattern.MISSING_ON_CONFLICT,
            sql_snippet="INSERT VALUES (2);",
            line_number=2,
            file_path="seeds_a.sql",
        )
        v3 = SeedViolation(
            pattern=SeedValidationPattern.NON_INSERT_STATEMENT,
            sql_snippet="CREATE TABLE test (id INT);",
            line_number=1,
            file_path="seeds_b.sql",
        )
        report.add_violation(v1)
        report.add_violation(v2)
        report.add_violation(v3)

        grouped = report.violations_by_file()
        assert len(grouped) == 2
        assert len(grouped["seeds_a.sql"]) == 2
        assert len(grouped["seeds_b.sql"]) == 1

    def test_report_to_dict(self) -> None:
        """Test report serialization."""
        report = SeedValidationReport()
        violation = SeedViolation(
            pattern=SeedValidationPattern.DOUBLE_SEMICOLON,
            sql_snippet="INSERT VALUES (1);;",
            line_number=1,
            file_path="seeds.sql",
        )
        report.add_violation(violation)
        report.add_file_scanned("seeds.sql")

        data = report.to_dict()
        assert data["violation_count"] == 1
        assert data["files_scanned"] == 1
        assert data["has_violations"] is True
        assert len(data["violations"]) == 1
        assert "seeds.sql" in data["scanned_files"]

    def test_report_str(self) -> None:
        """Test report string representation."""
        report = SeedValidationReport()
        report.add_file_scanned("seeds.sql")
        str_repr = str(report)
        assert "1 files scanned" in str_repr
        assert "0 violations" in str_repr


class TestDoublesemicolonDetection:
    """Test detection of double semicolons in seed files."""

    def test_detect_double_semicolon(self) -> None:
        """Test that double semicolons are detected."""
        from confiture.core.seed_validation.patterns import (
            detect_seed_issues,
        )

        sql = "INSERT INTO users VALUES (1, 'test');;"
        issues = detect_seed_issues(sql)
        assert len(issues) > 0
        assert any(i.pattern == SeedValidationPattern.DOUBLE_SEMICOLON for i in issues)

    def test_detect_double_semicolon_line_number(self) -> None:
        """Test that line number is correct for double semicolon."""
        from confiture.core.seed_validation.patterns import (
            detect_seed_issues,
        )

        sql = "INSERT INTO users VALUES (1, 'test');\nINSERT INTO products VALUES (1);;"
        issues = detect_seed_issues(sql)
        double_semi = [i for i in issues if i.pattern == SeedValidationPattern.DOUBLE_SEMICOLON]
        assert len(double_semi) > 0
        assert double_semi[0].line_number == 2

    def test_no_double_semicolon_false_positive(self) -> None:
        """Test that single semicolons don't trigger error."""
        from confiture.core.seed_validation.patterns import (
            detect_seed_issues,
        )

        sql = "INSERT INTO users VALUES (1, 'test');"
        issues = detect_seed_issues(sql)
        assert not any(i.pattern == SeedValidationPattern.DOUBLE_SEMICOLON for i in issues)


class TestDDLDetection:
    """Test detection of DDL statements in seed files."""

    def test_detect_create_table_in_seeds(self) -> None:
        """Test that CREATE TABLE in seeds is detected."""
        from confiture.core.seed_validation.patterns import (
            detect_seed_issues,
        )

        sql = "CREATE TABLE users (id INT);\nINSERT INTO users VALUES (1);"
        issues = detect_seed_issues(sql)
        assert any(i.pattern == SeedValidationPattern.NON_INSERT_STATEMENT for i in issues)

    def test_detect_alter_table_in_seeds(self) -> None:
        """Test that ALTER TABLE in seeds is detected."""
        from confiture.core.seed_validation.patterns import (
            detect_seed_issues,
        )

        sql = "ALTER TABLE users ADD COLUMN email VARCHAR(255);"
        issues = detect_seed_issues(sql)
        assert any(i.pattern == SeedValidationPattern.NON_INSERT_STATEMENT for i in issues)

    def test_detect_drop_table_in_seeds(self) -> None:
        """Test that DROP TABLE in seeds is detected."""
        from confiture.core.seed_validation.patterns import (
            detect_seed_issues,
        )

        sql = "DROP TABLE users;"
        issues = detect_seed_issues(sql)
        assert any(i.pattern == SeedValidationPattern.NON_INSERT_STATEMENT for i in issues)

    def test_no_ddl_for_insert_only(self) -> None:
        """Test that INSERT-only seeds don't trigger DDL detection."""
        from confiture.core.seed_validation.patterns import (
            detect_seed_issues,
        )

        sql = "INSERT INTO users VALUES (1, 'test');\nINSERT INTO products VALUES (1);"
        issues = detect_seed_issues(sql)
        assert not any(i.pattern == SeedValidationPattern.NON_INSERT_STATEMENT for i in issues)


class TestMissingOnConflictDetection:
    """Test detection of INSERT without ON CONFLICT."""

    def test_detect_insert_without_on_conflict(self) -> None:
        """Test that INSERT without ON CONFLICT is detected as warning."""
        from confiture.core.seed_validation.patterns import (
            detect_seed_issues,
        )

        sql = "INSERT INTO users (id, name) VALUES (1, 'test');"
        issues = detect_seed_issues(sql)
        assert any(i.pattern == SeedValidationPattern.MISSING_ON_CONFLICT for i in issues)

    def test_no_warning_for_insert_with_on_conflict(self) -> None:
        """Test that INSERT with ON CONFLICT doesn't trigger warning."""
        from confiture.core.seed_validation.patterns import (
            detect_seed_issues,
        )

        sql = "INSERT INTO users (id, name) VALUES (1, 'test') ON CONFLICT DO NOTHING;"
        issues = detect_seed_issues(sql)
        assert not any(i.pattern == SeedValidationPattern.MISSING_ON_CONFLICT for i in issues)

    def test_detect_insert_on_conflict_update(self) -> None:
        """Test that INSERT with ON CONFLICT UPDATE doesn't trigger warning."""
        from confiture.core.seed_validation.patterns import (
            detect_seed_issues,
        )

        sql = "INSERT INTO users (id, name) VALUES (1, 'test') ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;"
        issues = detect_seed_issues(sql)
        assert not any(i.pattern == SeedValidationPattern.MISSING_ON_CONFLICT for i in issues)


class TestSeedValidator:
    """Test SeedValidator class."""

    def test_validator_initialization(self) -> None:
        """Test creating a SeedValidator instance."""
        from confiture.core.seed_validation.validator import SeedValidator

        validator = SeedValidator()
        assert validator is not None

    def test_validate_sql_string(self, tmp_path) -> None:
        """Test validating SQL from a string."""
        from confiture.core.seed_validation.validator import SeedValidator

        validator = SeedValidator()
        sql = "INSERT INTO users VALUES (1, 'test');;"
        report = validator.validate_sql(sql, file_path="test.sql")
        assert report.has_violations
        assert report.violation_count > 0

    def test_validate_sql_no_violations(self) -> None:
        """Test SQL with no violations."""
        from confiture.core.seed_validation.validator import SeedValidator

        validator = SeedValidator()
        sql = "INSERT INTO users (id, name) VALUES (1, 'test') ON CONFLICT DO NOTHING;"
        report = validator.validate_sql(sql, file_path="test.sql")
        assert not report.has_violations

    def test_validate_file(self, tmp_path) -> None:
        """Test validating a single file."""
        from confiture.core.seed_validation.validator import SeedValidator

        # Create a test seed file
        seed_file = tmp_path / "seeds.sql"
        seed_file.write_text("INSERT INTO users VALUES (1);;")

        validator = SeedValidator()
        report = validator.validate_file(seed_file)
        assert report.has_violations
        assert str(seed_file) in report.scanned_files

    def test_validate_directory(self, tmp_path) -> None:
        """Test validating a directory of files."""
        from confiture.core.seed_validation.validator import SeedValidator

        # Create multiple seed files
        (tmp_path / "001_users.sql").write_text(
            "INSERT INTO users (id) VALUES (1) ON CONFLICT DO NOTHING;"
        )
        (tmp_path / "002_products.sql").write_text("INSERT INTO products VALUES (1);;")

        validator = SeedValidator()
        report = validator.validate_directory(tmp_path)
        assert report.has_violations
        assert report.files_scanned == 2

    def test_validate_directory_recursive(self, tmp_path) -> None:
        """Test recursive directory scanning."""
        from confiture.core.seed_validation.validator import SeedValidator

        # Create nested directories
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (tmp_path / "001.sql").write_text("INSERT INTO users VALUES (1) ON CONFLICT DO NOTHING;")
        (subdir / "002.sql").write_text("INSERT INTO products VALUES (1);;")

        validator = SeedValidator()
        report = validator.validate_directory(tmp_path, recursive=True)
        assert report.files_scanned == 2

    def test_ignore_patterns(self) -> None:
        """Test that ignored patterns don't appear in violations."""
        from confiture.core.seed_validation.validator import SeedValidator

        validator = SeedValidator(ignore_patterns=[SeedValidationPattern.DOUBLE_SEMICOLON])
        sql = "INSERT INTO users VALUES (1);;"
        report = validator.validate_sql(sql, file_path="test.sql")
        # Should not have DOUBLE_SEMICOLON violation
        assert not any(
            v.pattern == SeedValidationPattern.DOUBLE_SEMICOLON for v in report.violations
        )


class TestDatabaseSeedValidator:
    """Test DatabaseSeedValidator class."""

    def test_validator_initialization(self) -> None:
        """Test creating a DatabaseSeedValidator instance."""
        from confiture.core.seed_validation.database_validator import (
            DatabaseSeedValidator,
        )

        # Mock connection would be provided in integration tests
        validator = DatabaseSeedValidator(connection_string=None)
        assert validator is not None

    def test_validator_with_no_connection_skips_validation(self) -> None:
        """Test that validator handles missing connection gracefully."""
        from confiture.core.seed_validation.database_validator import (
            DatabaseSeedValidator,
        )

        validator = DatabaseSeedValidator(connection_string=None)
        sql = "INSERT INTO users (id) VALUES (1);"
        # Should not raise, just return no violations
        report = validator.validate_sql(sql, file_path="test.sql")
        assert report.files_scanned == 1


class TestAutoFix:
    """Test auto-fix functionality."""

    def test_auto_fix_on_conflict_missing(self) -> None:
        """Test adding ON CONFLICT to INSERT statements."""
        from confiture.core.seed_validation.fixer import SeedFixer

        fixer = SeedFixer()
        sql = "INSERT INTO users (id, name) VALUES (1, 'test');"
        fixed = fixer.fix_missing_on_conflict(sql)
        assert "ON CONFLICT" in fixed
        assert "DO NOTHING" in fixed

    def test_auto_fix_no_change_if_already_present(self) -> None:
        """Test that ON CONFLICT is not duplicated."""
        from confiture.core.seed_validation.fixer import SeedFixer

        fixer = SeedFixer()
        sql = "INSERT INTO users (id, name) VALUES (1, 'test') ON CONFLICT DO NOTHING;"
        fixed = fixer.fix_missing_on_conflict(sql)
        assert fixed == sql

    def test_auto_fix_dry_run(self, tmp_path) -> None:
        """Test that dry-run doesn't modify files."""
        from confiture.core.seed_validation.fixer import SeedFixer

        seed_file = tmp_path / "seeds.sql"
        original_sql = "INSERT INTO users (id) VALUES (1);"
        seed_file.write_text(original_sql)

        fixer = SeedFixer()
        result = fixer.fix_file(seed_file, dry_run=True)

        # File should not be modified
        assert seed_file.read_text() == original_sql
        assert result.dry_run is True
        assert result.fixes_applied > 0

    def test_auto_fix_applies_changes(self, tmp_path) -> None:
        """Test that auto-fix modifies files when not dry-run."""
        from confiture.core.seed_validation.fixer import SeedFixer

        seed_file = tmp_path / "seeds.sql"
        original_sql = "INSERT INTO users (id) VALUES (1);"
        seed_file.write_text(original_sql)

        fixer = SeedFixer()
        result = fixer.fix_file(seed_file, dry_run=False)

        # File should be modified
        fixed_sql = seed_file.read_text()
        assert fixed_sql != original_sql
        assert "ON CONFLICT" in fixed_sql
        assert result.fixes_applied > 0
