"""Tests for security validation module."""

import logging
from pathlib import Path

import pytest

from confiture.core.security.validation import (
    MAX_IDENTIFIER_LENGTH,
    MAX_PATH_LENGTH,
    MAX_SQL_LENGTH,
    ValidationError,
    sanitize_log_message,
    validate_config,
    validate_environment,
    validate_identifier,
    validate_path,
    validate_sql,
)


class TestValidateIdentifier:
    """Tests for validate_identifier function."""

    def test_valid_simple_identifier(self):
        """Test valid simple identifiers."""
        assert validate_identifier("users") == "users"
        assert validate_identifier("user_accounts") == "user_accounts"
        assert validate_identifier("_private") == "_private"
        assert validate_identifier("Table1") == "Table1"

    def test_valid_identifier_with_numbers(self):
        """Test identifiers with numbers."""
        assert validate_identifier("user2") == "user2"
        assert validate_identifier("table_123") == "table_123"

    def test_empty_identifier_raises(self):
        """Test empty identifier raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_identifier("")
        assert "Empty" in str(exc_info.value)

    def test_none_identifier_raises(self):
        """Test None identifier raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_identifier(None)

    def test_identifier_too_long_raises(self):
        """Test identifier exceeding max length raises."""
        long_name = "a" * (MAX_IDENTIFIER_LENGTH + 1)
        with pytest.raises(ValidationError) as exc_info:
            validate_identifier(long_name)
        assert "maximum length" in str(exc_info.value)

    def test_identifier_at_max_length_ok(self):
        """Test identifier at exactly max length is OK."""
        name = "a" * MAX_IDENTIFIER_LENGTH
        assert validate_identifier(name) == name

    def test_identifier_starting_with_number_raises(self):
        """Test identifier starting with number raises."""
        with pytest.raises(ValidationError) as exc_info:
            validate_identifier("123_table")
        assert "Must start with letter" in str(exc_info.value)

    def test_identifier_with_special_chars_raises(self):
        """Test identifier with special characters raises."""
        invalid_names = [
            "user-name",  # hyphen
            "user.name",  # dot
            "user name",  # space
            "user@name",  # at sign
            "user$name",  # dollar
        ]
        for name in invalid_names:
            with pytest.raises(ValidationError):
                validate_identifier(name)

    @pytest.mark.parametrize(
        "malicious_input",
        [
            "'; DROP TABLE users; --",
            "1; DELETE FROM migrations",
            "x' OR '1'='1",
            "Robert'); DROP TABLE Students;--",
            "users; --",
            "name\x00injection",
        ],
    )
    def test_sql_injection_patterns_rejected(self, malicious_input):
        """Test SQL injection attempts are rejected."""
        with pytest.raises(ValidationError):
            validate_identifier(malicious_input)

    @pytest.mark.parametrize(
        "reserved_word",
        [
            "select",
            "SELECT",
            "insert",
            "update",
            "delete",
            "drop",
            "create",
            "alter",
            "table",
            "from",
            "where",
        ],
    )
    def test_reserved_words_rejected(self, reserved_word):
        """Test SQL reserved words are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_identifier(reserved_word)
        assert "reserved word" in str(exc_info.value).lower()

    def test_custom_context_in_error(self):
        """Test custom context appears in error message."""
        with pytest.raises(ValidationError) as exc_info:
            validate_identifier("", context="table name")
        assert "table name" in str(exc_info.value)


class TestValidatePath:
    """Tests for validate_path function."""

    def test_valid_relative_path(self, tmp_path):
        """Test valid relative path."""
        result = validate_path("db/migrations/001.py")
        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_valid_absolute_path(self, tmp_path):
        """Test valid absolute path."""
        test_file = tmp_path / "test.py"
        test_file.touch()
        result = validate_path(str(test_file))
        assert result == test_file.resolve()

    def test_path_must_exist(self, tmp_path):
        """Test path existence check."""
        with pytest.raises(ValidationError) as exc_info:
            validate_path(tmp_path / "nonexistent.py", must_exist=True)
        assert "does not exist" in str(exc_info.value)

    def test_path_exists_check_passes(self, tmp_path):
        """Test path existence check passes for existing file."""
        test_file = tmp_path / "exists.py"
        test_file.touch()
        result = validate_path(test_file, must_exist=True)
        assert result.exists()

    def test_path_too_long_raises(self):
        """Test path exceeding max length raises."""
        long_path = "a" * (MAX_PATH_LENGTH + 1)
        with pytest.raises(ValidationError) as exc_info:
            validate_path(long_path)
        assert "maximum length" in str(exc_info.value)

    def test_null_byte_in_path_raises(self):
        """Test path with null byte raises."""
        with pytest.raises(ValidationError) as exc_info:
            validate_path("test\x00file.py")
        assert "null byte" in str(exc_info.value)

    def test_path_traversal_prevented(self, tmp_path):
        """Test path traversal is prevented with base_dir."""
        base_dir = tmp_path / "migrations"
        base_dir.mkdir()

        with pytest.raises(ValidationError) as exc_info:
            validate_path("../../../etc/passwd", base_dir=base_dir)
        assert "outside allowed directory" in str(exc_info.value)

    def test_path_within_base_dir_ok(self, tmp_path):
        """Test path within base_dir is allowed."""
        base_dir = tmp_path / "migrations"
        base_dir.mkdir()
        test_file = base_dir / "001.py"
        test_file.touch()

        # Use absolute path within base_dir
        result = validate_path(test_file, base_dir=base_dir)
        assert result == test_file.resolve()

    def test_path_object_input(self, tmp_path):
        """Test Path object as input."""
        test_file = tmp_path / "test.py"
        test_file.touch()
        result = validate_path(test_file)
        assert isinstance(result, Path)


class TestValidateEnvironment:
    """Tests for validate_environment function."""

    @pytest.mark.parametrize(
        "env,expected",
        [
            ("local", "local"),
            ("LOCAL", "local"),
            ("development", "development"),
            ("dev", "dev"),
            ("test", "test"),
            ("testing", "testing"),
            ("staging", "staging"),
            ("production", "production"),
            ("prod", "prod"),
            ("  staging  ", "staging"),
        ],
    )
    def test_valid_environments(self, env, expected):
        """Test valid environment names."""
        assert validate_environment(env) == expected

    def test_empty_environment_raises(self):
        """Test empty environment raises."""
        with pytest.raises(ValidationError) as exc_info:
            validate_environment("")
        assert "Empty" in str(exc_info.value)

    def test_invalid_environment_raises(self):
        """Test invalid environment raises."""
        with pytest.raises(ValidationError) as exc_info:
            validate_environment("hacker")
        assert "Invalid environment" in str(exc_info.value)
        assert "Allowed:" in str(exc_info.value)

    def test_non_string_environment_raises(self):
        """Test non-string environment raises."""
        with pytest.raises(ValidationError):
            validate_environment(123)


class TestValidateSQL:
    """Tests for validate_sql function."""

    def test_valid_simple_sql(self):
        """Test valid simple SQL."""
        sql = "SELECT * FROM users"
        assert validate_sql(sql) == sql

    def test_valid_multiline_sql(self):
        """Test valid multiline SQL."""
        sql = """
        SELECT id, name
        FROM users
        WHERE active = true
        """
        result = validate_sql(sql)
        assert "SELECT" in result

    def test_empty_sql_raises(self):
        """Test empty SQL raises."""
        with pytest.raises(ValidationError) as exc_info:
            validate_sql("")
        assert "Empty SQL" in str(exc_info.value)

    def test_whitespace_only_sql_raises(self):
        """Test whitespace-only SQL raises."""
        with pytest.raises(ValidationError):
            validate_sql("   \n\t  ")

    def test_sql_too_long_raises(self):
        """Test SQL exceeding max length raises."""
        long_sql = "SELECT " + "x" * MAX_SQL_LENGTH
        with pytest.raises(ValidationError) as exc_info:
            validate_sql(long_sql)
        assert "maximum length" in str(exc_info.value)

    @pytest.mark.parametrize(
        "dangerous_sql",
        [
            "SELECT 1; DROP TABLE users",
            "SELECT 1; DELETE FROM users WHERE 1=1",
            "SELECT 1; TRUNCATE users",
            "SELECT 1 -- comment injection",
            "SELECT /* comment */ 1",
            "SELECT 1; ALTER TABLE users OWNER TO hacker",
        ],
    )
    def test_dangerous_patterns_rejected(self, dangerous_sql):
        """Test dangerous SQL patterns are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_sql(dangerous_sql)
        assert "dangerous pattern" in str(exc_info.value).lower()

    def test_dangerous_patterns_allowed_when_flag_set(self):
        """Test dangerous patterns allowed with allow_dangerous=True."""
        sql = "SELECT 1; DROP TABLE users"
        result = validate_sql(sql, allow_dangerous=True)
        assert result == sql

    def test_valid_migration_sql(self):
        """Test valid migration SQL (single statement)."""
        sql = """
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
        result = validate_sql(sql)
        assert "CREATE TABLE" in result


class TestValidateConfig:
    """Tests for validate_config function."""

    def test_valid_config(self):
        """Test valid configuration."""
        config = {"database_url": "postgresql://user:pass@localhost/db"}
        result = validate_config(config)
        assert result == config

    def test_nested_database_url(self):
        """Test nested database URL."""
        config = {"database": {"url": "postgresql://user:pass@localhost/db"}}
        result = validate_config(config)
        assert result == config

    def test_invalid_scheme_raises(self):
        """Test invalid database URL scheme raises."""
        config = {"database_url": "mysql://user:pass@localhost/db"}
        with pytest.raises(ValidationError) as exc_info:
            validate_config(config)
        assert "Invalid database URL scheme" in str(exc_info.value)

    def test_non_dict_config_raises(self):
        """Test non-dict config raises."""
        with pytest.raises(ValidationError):
            validate_config("not a dict")

    def test_embedded_credentials_warning(self, caplog):
        """Test warning for embedded credentials."""
        config = {"database_url": "postgresql://user:password@localhost/db"}
        with caplog.at_level(logging.WARNING):
            validate_config(config)
        assert "embedded credentials" in caplog.text.lower()


class TestSanitizeLogMessage:
    """Tests for sanitize_log_message function."""

    @pytest.mark.parametrize(
        "message,should_not_contain",
        [
            ("password=secret123", "secret123"),
            ("password: secret123", "secret123"),
            ("PASSWORD=SECRET", "SECRET"),
            ("passwd=mypass", "mypass"),
        ],
    )
    def test_password_redacted(self, message, should_not_contain):
        """Test passwords are redacted."""
        sanitized = sanitize_log_message(message)
        assert should_not_contain not in sanitized
        assert "***" in sanitized

    @pytest.mark.parametrize(
        "message,should_not_contain",
        [
            ("secret=my_secret", "my_secret"),
            ("token=abc123xyz", "abc123xyz"),
            ("api_key=key123", "key123"),
            ("api-key=key123", "key123"),
            ("auth_token=tok123", "tok123"),
            ("access_key=acc123", "acc123"),
            ("private_key=priv123", "priv123"),
        ],
    )
    def test_secrets_redacted(self, message, should_not_contain):
        """Test various secrets are redacted."""
        sanitized = sanitize_log_message(message)
        assert should_not_contain not in sanitized
        assert "***" in sanitized

    @pytest.mark.parametrize(
        "message,should_not_contain",
        [
            ("postgresql://user:password@host/db", "password"),
            ("postgres://admin:secret@localhost:5432/mydb", "secret"),
        ],
    )
    def test_database_urls_redacted(self, message, should_not_contain):
        """Test database URLs have credentials redacted."""
        sanitized = sanitize_log_message(message)
        assert should_not_contain not in sanitized
        assert "***@" in sanitized

    @pytest.mark.parametrize(
        "message,should_not_contain",
        [
            ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"),
            ("Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ],
    )
    def test_auth_headers_redacted(self, message, should_not_contain):
        """Test auth headers are redacted."""
        sanitized = sanitize_log_message(message)
        assert should_not_contain not in sanitized
        assert "***" in sanitized

    def test_empty_message_unchanged(self):
        """Test empty message returns empty."""
        assert sanitize_log_message("") == ""
        assert sanitize_log_message(None) is None

    def test_message_without_secrets_unchanged(self):
        """Test message without secrets is unchanged."""
        message = "SELECT * FROM users WHERE id = 123"
        assert sanitize_log_message(message) == message

    def test_multiple_secrets_all_redacted(self):
        """Test multiple secrets in one message are all redacted."""
        message = "Connecting with password=secret123 and token=abc456"
        sanitized = sanitize_log_message(message)
        assert "secret123" not in sanitized
        assert "abc456" not in sanitized
        assert sanitized.count("***") >= 2
