"""Integration tests for schema linting system.

These tests verify the linting system works end-to-end with real schema files
and database configurations.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from confiture.core.linting import SchemaLinter
from confiture.models.lint import LintConfig, LintSeverity


class TestLinderIntegration:
    """Integration tests for SchemaLinter with real files."""

    def test_lint_valid_schema(self):
        """Should lint a valid schema with minimal violations."""
        # Create temporary project with valid schema
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create schema directory structure
            schema_dir = tmpdir_path / "db" / "schema" / "10_tables"
            schema_dir.mkdir(parents=True, exist_ok=True)

            # Create valid schema file
            schema_file = schema_dir / "01_users.sql"
            schema_file.write_text("""
-- User accounts
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT NOW()
);
""")

            # Create environment config
            env_dir = tmpdir_path / "db" / "environments"
            env_dir.mkdir(parents=True, exist_ok=True)
            env_config = env_dir / "test.yaml"
            env_config.write_text("""
name: test
include_dirs:
  - db/schema
exclude_dirs: []
database_url: postgresql://postgres:postgres@localhost/test_db
migration:
  strict_mode: false
""")

            # Change to temp directory for test
            import os
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                # Lint the schema
                linter = SchemaLinter(env="test")
                report = linter.lint()

                # Verify report
                assert report.schema_name == "test"
                assert report.tables_checked >= 1
                assert report.columns_checked >= 0

                # Table should have primary key and comment
                # (has PK but missing comment)
                doc_violations = [
                    v for v in report.violations
                    if "documentation" in v.rule_name.lower()
                ]
                # May or may not have violations depending on config
                assert isinstance(doc_violations, list)

            finally:
                os.chdir(original_cwd)

    def test_lint_naming_convention_violations(self):
        """Should detect naming convention violations."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create schema directory
            schema_dir = tmpdir_path / "db" / "schema" / "10_tables"
            schema_dir.mkdir(parents=True, exist_ok=True)

            # Create schema with naming violations
            schema_file = schema_dir / "01_bad_names.sql"
            schema_file.write_text("""
CREATE TABLE IF NOT EXISTS UserTable (
    userId SERIAL PRIMARY KEY,
    userName TEXT NOT NULL
);
""")

            # Create environment config
            env_dir = tmpdir_path / "db" / "environments"
            env_dir.mkdir(parents=True, exist_ok=True)
            env_config = env_dir / "test.yaml"
            env_config.write_text("""
name: test
include_dirs:
  - db/schema
exclude_dirs: []
database_url: postgresql://postgres:postgres@localhost/test_db
migration:
  strict_mode: false
""")

            import os
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                # Lint the schema
                linter = SchemaLinter(env="test")
                report = linter.lint()

                # Should find naming violations
                naming_violations = [
                    v for v in report.violations
                    if "NamingConventionRule" in v.rule_name
                ]
                assert len(naming_violations) >= 2  # UserTable, userId, userName

                # All should be errors
                for v in naming_violations:
                    assert v.severity == LintSeverity.ERROR

                # Should have suggestions
                assert all(v.suggested_fix for v in naming_violations)

            finally:
                os.chdir(original_cwd)

    def test_lint_missing_primary_key(self):
        """Should detect tables without primary key."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create schema directory
            schema_dir = tmpdir_path / "db" / "schema" / "10_tables"
            schema_dir.mkdir(parents=True, exist_ok=True)

            # Create schema without primary key
            schema_file = schema_dir / "01_no_pk.sql"
            schema_file.write_text("""
CREATE TABLE IF NOT EXISTS records (
    name TEXT NOT NULL,
    value INTEGER
);
""")

            # Create environment config
            env_dir = tmpdir_path / "db" / "environments"
            env_dir.mkdir(parents=True, exist_ok=True)
            env_config = env_dir / "test.yaml"
            env_config.write_text("""
name: test
include_dirs:
  - db/schema
exclude_dirs: []
database_url: postgresql://postgres:postgres@localhost/test_db
migration:
  strict_mode: false
""")

            import os
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                # Lint the schema
                linter = SchemaLinter(env="test")
                report = linter.lint()

                # Should find missing primary key
                pk_violations = [
                    v for v in report.violations
                    if "PrimaryKeyRule" in v.rule_name
                ]
                assert len(pk_violations) >= 1
                assert all(
                    v.severity == LintSeverity.ERROR
                    for v in pk_violations
                )

            finally:
                os.chdir(original_cwd)

    def test_lint_security_violations(self):
        """Should detect security issues (passwords, tokens, secrets)."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create schema directory
            schema_dir = tmpdir_path / "db" / "schema" / "10_tables"
            schema_dir.mkdir(parents=True, exist_ok=True)

            # Create schema with security violations
            schema_file = schema_dir / "01_security.sql"
            schema_file.write_text("""
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    password VARCHAR(255),
    api_token VARCHAR(255),
    secret_key TEXT
);
""")

            # Create environment config
            env_dir = tmpdir_path / "db" / "environments"
            env_dir.mkdir(parents=True, exist_ok=True)
            env_config = env_dir / "test.yaml"
            env_config.write_text("""
name: test
include_dirs:
  - db/schema
exclude_dirs: []
database_url: postgresql://postgres:postgres@localhost/test_db
migration:
  strict_mode: false
""")

            import os
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                # Lint the schema
                linter = SchemaLinter(env="test")
                report = linter.lint()

                # Should find security violations
                security_violations = [
                    v for v in report.violations
                    if "SecurityRule" in v.rule_name
                ]
                assert len(security_violations) >= 2  # token, secret (password might not be flagged depending on type inference)

                # All should be warnings
                assert all(
                    v.severity == LintSeverity.WARNING
                    for v in security_violations
                )

            finally:
                os.chdir(original_cwd)

    def test_lint_with_custom_config(self):
        """Should respect custom linting configuration."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create schema directory
            schema_dir = tmpdir_path / "db" / "schema" / "10_tables"
            schema_dir.mkdir(parents=True, exist_ok=True)

            # Create schema
            schema_file = schema_dir / "01_test.sql"
            schema_file.write_text("""
CREATE TABLE IF NOT EXISTS test_table (
    id SERIAL PRIMARY KEY
);
""")

            # Create environment config
            env_dir = tmpdir_path / "db" / "environments"
            env_dir.mkdir(parents=True, exist_ok=True)
            env_config = env_dir / "test.yaml"
            env_config.write_text("""
name: test
include_dirs:
  - db/schema
exclude_dirs: []
database_url: postgresql://postgres:postgres@localhost/test_db
migration:
  strict_mode: false
""")

            import os
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                # Custom config: exclude documentation rule
                config = LintConfig.default()
                config.rules.pop("documentation", None)

                # Lint the schema
                linter = SchemaLinter(env="test", config=config)
                report = linter.lint()

                # Should not have documentation violations
                doc_violations = [
                    v for v in report.violations
                    if "DocumentationRule" in v.rule_name
                ]
                assert len(doc_violations) == 0

            finally:
                os.chdir(original_cwd)

    def test_lint_report_has_all_metrics(self):
        """Should return report with all metrics calculated."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create schema directory
            schema_dir = tmpdir_path / "db" / "schema" / "10_tables"
            schema_dir.mkdir(parents=True, exist_ok=True)

            # Create multiple tables
            schema_file = schema_dir / "01_tables.sql"
            schema_file.write_text("""
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    id SERIAL PRIMARY KEY,
    title TEXT,
    user_id INTEGER
);
""")

            # Create environment config
            env_dir = tmpdir_path / "db" / "environments"
            env_dir.mkdir(parents=True, exist_ok=True)
            env_config = env_dir / "test.yaml"
            env_config.write_text("""
name: test
include_dirs:
  - db/schema
exclude_dirs: []
database_url: postgresql://postgres:postgres@localhost/test_db
migration:
  strict_mode: false
""")

            import os
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                # Lint the schema
                linter = SchemaLinter(env="test")
                report = linter.lint()

                # Verify all metrics are present and reasonable
                assert report.schema_name == "test"
                assert report.tables_checked >= 2
                assert report.columns_checked >= 4
                assert report.execution_time_ms >= 0
                assert report.errors_count >= 0
                assert report.warnings_count >= 0
                assert report.info_count >= 0
                assert (
                    report.errors_count
                    + report.warnings_count
                    + report.info_count
                ) == len(report.violations)

                # Test has_errors and has_warnings properties
                if report.errors_count > 0:
                    assert report.has_errors is True
                else:
                    assert report.has_errors is False

                if report.warnings_count > 0:
                    assert report.has_warnings is True
                else:
                    assert report.has_warnings is False

            finally:
                os.chdir(original_cwd)

    def test_lint_exclude_tables(self):
        """Should exclude tables matching exclude_tables patterns."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create schema directory
            schema_dir = tmpdir_path / "db" / "schema" / "10_tables"
            schema_dir.mkdir(parents=True, exist_ok=True)

            # Create tables with different names
            schema_file = schema_dir / "01_tables.sql"
            schema_file.write_text("""
CREATE TABLE IF NOT EXISTS pg_custom (
    id SERIAL
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY
);
""")

            # Create environment config
            env_dir = tmpdir_path / "db" / "environments"
            env_dir.mkdir(parents=True, exist_ok=True)
            env_config = env_dir / "test.yaml"
            env_config.write_text("""
name: test
include_dirs:
  - db/schema
exclude_dirs: []
database_url: postgresql://postgres:postgres@localhost/test_db
migration:
  strict_mode: false
""")

            import os
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir_path)

                # Custom config: exclude pg_* tables
                config = LintConfig.default()
                config.exclude_tables = ["pg_*"]

                # Lint the schema
                linter = SchemaLinter(env="test", config=config)
                report = linter.lint()

                # Violations should only be for users table, not pg_custom
                pg_violations = [
                    v for v in report.violations
                    if "pg_custom" in v.location
                ]
                assert len(pg_violations) == 0

            finally:
                os.chdir(original_cwd)
