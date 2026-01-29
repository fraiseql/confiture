"""Tests for IdempotencyValidator class."""

from pathlib import Path
from textwrap import dedent

from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.validator import IdempotencyValidator


class TestIdempotencyValidator:
    """Tests for the IdempotencyValidator class."""

    def test_validate_sql_string(self):
        """Validator can validate SQL passed as a string."""
        validator = IdempotencyValidator()
        sql = "CREATE TABLE users (id INT PRIMARY KEY);"

        report = validator.validate_sql(sql, file_path="test.sql")

        assert report.has_violations
        assert report.violation_count == 1
        assert report.violations[0].pattern == IdempotencyPattern.CREATE_TABLE

    def test_validate_file(self, tmp_path: Path):
        """Validator can validate a SQL file from disk."""
        migration_file = tmp_path / "001_init.up.sql"
        migration_file.write_text("CREATE TABLE users (id INT);\nCREATE INDEX idx ON users(id);")

        validator = IdempotencyValidator()
        report = validator.validate_file(migration_file)

        assert report.has_violations
        assert report.violation_count == 2
        assert str(migration_file) in report.scanned_files

    def test_validate_directory(self, tmp_path: Path):
        """Validator can scan all migration files in a directory."""
        # Create migration files
        (tmp_path / "001_init.up.sql").write_text("CREATE TABLE users (id INT);")
        (tmp_path / "002_add_index.up.sql").write_text("CREATE INDEX idx ON users(id);")
        (tmp_path / "003_safe.up.sql").write_text("CREATE TABLE IF NOT EXISTS orders (id INT);")
        # Non-migration files should be ignored
        (tmp_path / "README.md").write_text("# Migrations")
        (tmp_path / "test.py").write_text("print('hello')")

        validator = IdempotencyValidator()
        report = validator.validate_directory(tmp_path)

        assert report.files_scanned == 3
        assert report.violation_count == 2  # From files 001 and 002

    def test_validate_directory_filters_by_pattern(self, tmp_path: Path):
        """Validator can filter files by glob pattern."""
        (tmp_path / "001_init.up.sql").write_text("CREATE TABLE users (id INT);")
        (tmp_path / "001_init.down.sql").write_text("DROP TABLE users;")

        validator = IdempotencyValidator()
        # Only validate .up.sql files
        report = validator.validate_directory(tmp_path, pattern="*.up.sql")

        assert report.files_scanned == 1
        assert any("001_init.up.sql" in f for f in report.scanned_files)

    def test_empty_file_returns_clean_report(self, tmp_path: Path):
        """Empty SQL files produce no violations."""
        empty_file = tmp_path / "empty.up.sql"
        empty_file.write_text("")

        validator = IdempotencyValidator()
        report = validator.validate_file(empty_file)

        assert not report.has_violations
        assert report.files_scanned == 1

    def test_idempotent_migration_returns_clean_report(self):
        """Fully idempotent SQL produces no violations."""
        sql = dedent("""
            CREATE TABLE IF NOT EXISTS users (id INT);
            CREATE INDEX IF NOT EXISTS idx_users ON users(id);
            CREATE OR REPLACE FUNCTION fn_test() RETURNS VOID AS $$ BEGIN END; $$ LANGUAGE plpgsql;
            DROP TABLE IF EXISTS old_table;
        """)

        validator = IdempotencyValidator()
        report = validator.validate_sql(sql, file_path="test.sql")

        assert not report.has_violations

    def test_violations_include_correct_file_path(self, tmp_path: Path):
        """Violations reference the correct source file."""
        migration = tmp_path / "migrations" / "001_init.up.sql"
        migration.parent.mkdir(parents=True)
        migration.write_text("CREATE TABLE users (id INT);")

        validator = IdempotencyValidator()
        report = validator.validate_file(migration)

        assert report.violations[0].file_path == str(migration)

    def test_violations_include_line_numbers(self):
        """Violations include accurate line numbers."""
        sql = dedent("""
            -- Line 1: comment
            -- Line 2: comment
            CREATE TABLE users (id INT);
            -- Line 4: comment
            CREATE INDEX idx ON users(id);
        """).strip()

        validator = IdempotencyValidator()
        report = validator.validate_sql(sql, file_path="test.sql")

        # CREATE TABLE on line 3, CREATE INDEX on line 5
        table_violation = next(
            v for v in report.violations if v.pattern == IdempotencyPattern.CREATE_TABLE
        )
        index_violation = next(
            v for v in report.violations if v.pattern == IdempotencyPattern.CREATE_INDEX
        )

        assert table_violation.line_number == 3
        assert index_violation.line_number == 5


class TestValidatorConfiguration:
    """Tests for validator configuration options."""

    def test_ignore_patterns_option(self):
        """Validator can ignore specific patterns."""
        sql = dedent("""
            CREATE TABLE users (id INT);
            CREATE INDEX idx ON users(id);
        """)

        validator = IdempotencyValidator(ignore_patterns=[IdempotencyPattern.CREATE_INDEX])
        report = validator.validate_sql(sql, file_path="test.sql")

        # Only CREATE TABLE should be flagged
        assert report.violation_count == 1
        assert report.violations[0].pattern == IdempotencyPattern.CREATE_TABLE

    def test_severity_threshold_option(self):
        """Validator respects severity threshold configuration."""
        # This test verifies the config is accepted - actual severity
        # filtering would be used in CLI/reporting
        validator = IdempotencyValidator(severity="warning")

        sql = "CREATE TABLE users (id INT);"
        report = validator.validate_sql(sql, file_path="test.sql")

        # Validation still works
        assert report.has_violations


class TestValidatorEdgeCases:
    """Tests for edge cases and complex SQL."""

    def test_handles_dollar_quoted_strings(self):
        """Correctly handles PostgreSQL dollar-quoted strings."""
        sql = dedent("""
            CREATE OR REPLACE FUNCTION test_fn() RETURNS VOID AS $$
            BEGIN
                -- This CREATE TABLE is inside a string, not real SQL
                RAISE NOTICE 'CREATE TABLE fake (id INT);';
            END;
            $$ LANGUAGE plpgsql;
        """)

        validator = IdempotencyValidator()
        report = validator.validate_sql(sql, file_path="test.sql")

        # CREATE OR REPLACE is idempotent, fake table in string should be ignored
        assert not report.has_violations

    def test_handles_comments(self):
        """Ignores SQL in comments."""
        sql = dedent("""
            -- CREATE TABLE commented_out (id INT);
            /* CREATE TABLE also_commented (id INT); */
            CREATE TABLE IF NOT EXISTS real_table (id INT);
        """)

        validator = IdempotencyValidator()
        report = validator.validate_sql(sql, file_path="test.sql")

        # Only real_table exists and it's idempotent
        assert not report.has_violations

    def test_handles_mixed_case_keywords(self):
        """Detects patterns regardless of keyword case."""
        sql = "create TABLE Users (id INT);"

        validator = IdempotencyValidator()
        report = validator.validate_sql(sql, file_path="test.sql")

        assert report.has_violations
        assert report.violations[0].pattern == IdempotencyPattern.CREATE_TABLE

    def test_handles_schema_qualified_names(self):
        """Detects patterns with schema-qualified names."""
        sql = "CREATE TABLE myschema.users (id INT);"

        validator = IdempotencyValidator()
        report = validator.validate_sql(sql, file_path="test.sql")

        assert report.has_violations
        assert "myschema.users" in report.violations[0].sql_snippet


class TestReportGeneration:
    """Tests for report generation features."""

    def test_report_summary(self):
        """Report provides a useful summary."""
        sql = dedent("""
            CREATE TABLE users (id INT);
            CREATE TABLE orders (id INT);
            CREATE INDEX idx ON users(id);
        """)

        validator = IdempotencyValidator()
        report = validator.validate_sql(sql, file_path="test.sql")

        summary = str(report)
        assert "3" in summary  # 3 violations
        assert "test.sql" in summary

    def test_report_json_serializable(self):
        """Report can be serialized to JSON-compatible dict."""
        import json

        sql = "CREATE TABLE users (id INT);"

        validator = IdempotencyValidator()
        report = validator.validate_sql(sql, file_path="test.sql")

        # Should not raise
        data = report.to_dict()
        json_str = json.dumps(data)

        assert "CREATE_TABLE" in json_str
        assert "test.sql" in json_str
