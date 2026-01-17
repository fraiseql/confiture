"""Tests for secure logging module."""

import logging
from io import StringIO

import pytest

from confiture.core.security.logging import (
    SecureFormatter,
    SecureLoggerAdapter,
    SensitiveValue,
    configure_secure_logging,
    get_secure_logger,
)


class TestSecureFormatter:
    """Tests for SecureFormatter class."""

    @pytest.fixture
    def formatter(self):
        """Create a SecureFormatter instance."""
        return SecureFormatter("%(message)s")

    @pytest.fixture
    def log_record(self):
        """Create a log record factory."""

        def _create(msg):
            return logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg=msg,
                args=(),
                exc_info=None,
            )

        return _create

    def test_redacts_password(self, formatter, log_record):
        """Test password is redacted."""
        record = log_record("password=secret123")
        formatted = formatter.format(record)
        assert "secret123" not in formatted
        assert "***" in formatted

    def test_redacts_database_url(self, formatter, log_record):
        """Test database URL credentials are redacted."""
        record = log_record("Connecting to postgresql://user:pass@host/db")
        formatted = formatter.format(record)
        assert "pass" not in formatted
        assert "postgresql://***@" in formatted

    def test_redacts_bearer_token(self, formatter, log_record):
        """Test Bearer token is redacted."""
        record = log_record("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJ0ZXN0IjoiZGF0YSJ9")
        formatted = formatter.format(record)
        assert "eyJhbGciOiJIUzI1NiJ9" not in formatted
        assert "Bearer ***" in formatted

    def test_redacts_aws_credentials(self, formatter, log_record):
        """Test AWS credentials are redacted."""
        record = log_record("AWS_SECRET_ACCESS_KEY=abcd1234 AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
        formatted = formatter.format(record)
        assert "abcd1234" not in formatted
        assert "AKIAIOSFODNN7EXAMPLE" not in formatted

    def test_redacts_json_password(self, formatter, log_record):
        """Test JSON password fields are redacted."""
        record = log_record('Config: {"password": "secret123", "user": "admin"}')
        formatted = formatter.format(record)
        assert "secret123" not in formatted

    def test_preserves_normal_message(self, formatter, log_record):
        """Test normal message is preserved."""
        record = log_record("Migration 001_users completed in 1.5s")
        formatted = formatter.format(record)
        assert formatted == "Migration 001_users completed in 1.5s"

    def test_multiple_secrets_redacted(self, formatter, log_record):
        """Test multiple secrets are all redacted."""
        record = log_record("password=secret1 token=secret2 api_key=secret3")
        formatted = formatter.format(record)
        assert "secret1" not in formatted
        assert "secret2" not in formatted
        assert "secret3" not in formatted


class TestSecureLoggerAdapter:
    """Tests for SecureLoggerAdapter class."""

    @pytest.fixture
    def logger_with_capture(self):
        """Create a logger that captures output."""
        logger = logging.getLogger("test_adapter")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(SecureFormatter("%(message)s"))
        logger.addHandler(handler)

        return logger, stream

    def test_adapter_sanitizes_messages(self, logger_with_capture):
        """Test adapter sanitizes messages."""
        logger, stream = logger_with_capture
        adapter = SecureLoggerAdapter(logger, {})

        adapter.info("Connecting with password=secret123")

        output = stream.getvalue()
        assert "secret123" not in output
        assert "***" in output

    def test_adapter_preserves_extras(self, logger_with_capture):
        """Test adapter preserves extra context."""
        logger, stream = logger_with_capture
        adapter = SecureLoggerAdapter(logger, {"extra_key": "extra_value"})

        adapter.info("Test message")
        # Extra should be preserved (not sanitized)
        assert adapter.extra == {"extra_key": "extra_value"}


class TestConfigureSecureLogging:
    """Tests for configure_secure_logging function."""

    def test_returns_logger(self):
        """Test function returns a logger."""
        logger = configure_secure_logging(logger_name="test_config")
        assert isinstance(logger, logging.Logger)

    def test_logger_has_secure_formatter(self):
        """Test logger has secure formatter."""
        logger = configure_secure_logging(logger_name="test_formatter")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0].formatter, SecureFormatter)

    def test_custom_format_string(self):
        """Test custom format string is used."""
        format_string = "CUSTOM: %(message)s"
        logger = configure_secure_logging(
            logger_name="test_custom_format", format_string=format_string
        )
        # Formatter should use custom format
        assert logger.handlers[0].formatter._fmt == format_string

    def test_custom_level(self):
        """Test custom level is set."""
        logger = configure_secure_logging(level=logging.DEBUG, logger_name="test_level")
        assert logger.level == logging.DEBUG

    def test_clears_existing_handlers(self):
        """Test existing handlers are cleared."""
        logger_name = "test_clear_handlers"
        logger = logging.getLogger(logger_name)

        # Add some handlers
        logger.addHandler(logging.StreamHandler())
        logger.addHandler(logging.StreamHandler())
        assert len(logger.handlers) == 2

        # Configure should clear them
        configure_secure_logging(logger_name=logger_name)
        assert len(logger.handlers) == 1


class TestGetSecureLogger:
    """Tests for get_secure_logger function."""

    def test_returns_adapter(self):
        """Test function returns SecureLoggerAdapter."""
        logger = get_secure_logger("test_get")
        assert isinstance(logger, SecureLoggerAdapter)

    def test_adapter_has_correct_name(self):
        """Test adapter wraps correctly named logger."""
        logger = get_secure_logger("confiture.migration")
        assert logger.logger.name == "confiture.migration"


class TestSensitiveValue:
    """Tests for SensitiveValue class."""

    def test_str_returns_redacted(self):
        """Test str() returns redacted value."""
        value = SensitiveValue("secret123")
        assert str(value) == "***"

    def test_repr_returns_redacted(self):
        """Test repr() returns redacted value."""
        value = SensitiveValue("secret123")
        assert repr(value) == "SensitiveValue(***)"

    def test_get_value_returns_actual(self):
        """Test get_value() returns actual value."""
        value = SensitiveValue("secret123")
        assert value.get_value() == "secret123"

    def test_fstring_redacted(self):
        """Test f-string formatting redacts value."""
        value = SensitiveValue("secret123")
        result = f"Password is {value}"
        assert "secret123" not in result
        assert "***" in result

    def test_equality_compares_values(self):
        """Test equality compares actual values."""
        value1 = SensitiveValue("secret")
        value2 = SensitiveValue("secret")
        value3 = SensitiveValue("other")

        assert value1 == value2
        assert value1 != value3
        assert value1 == "secret"  # Compare with raw value

    def test_hashable(self):
        """Test SensitiveValue is hashable."""
        value = SensitiveValue("secret")
        hash_value = hash(value)
        assert isinstance(hash_value, int)

    def test_can_use_in_dict(self):
        """Test SensitiveValue can be used as dict key."""
        value = SensitiveValue("key")
        d = {value: "data"}
        assert d[value] == "data"

    def test_different_types(self):
        """Test SensitiveValue works with different types."""
        # String
        assert SensitiveValue("secret").get_value() == "secret"

        # Number
        assert SensitiveValue(12345).get_value() == 12345

        # Dict
        secret_dict = {"api_key": "abc123"}
        assert SensitiveValue(secret_dict).get_value() == secret_dict


class TestIntegration:
    """Integration tests for secure logging."""

    def test_full_logging_flow(self):
        """Test complete logging flow with secure redaction."""
        # Configure
        logger = configure_secure_logging(level=logging.DEBUG, logger_name="test_integration")

        # Capture output
        stream = StringIO()
        logger.handlers[0].stream = stream

        # Log sensitive data
        logger.info("Connecting to postgresql://admin:supersecret@prod.db.com/app")
        logger.info("Using API key: api_key=12345abcde")
        logger.info("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.test")

        output = stream.getvalue()

        # Verify redaction
        assert "supersecret" not in output
        assert "12345abcde" not in output
        assert "eyJhbGciOiJSUzI1NiJ9" not in output

        # Verify structure preserved
        assert "postgresql://***@prod.db.com/app" in output
        assert "api_key=***" in output
        assert "Bearer ***" in output

    def test_exception_logging_redacted(self):
        """Test exceptions with sensitive data are redacted."""
        logger = configure_secure_logging(logger_name="test_exception")

        stream = StringIO()
        logger.handlers[0].stream = stream

        try:
            raise ValueError("Connection failed: password=secret123")
        except ValueError:
            logger.exception("Error occurred")

        output = stream.getvalue()
        assert "secret123" not in output
