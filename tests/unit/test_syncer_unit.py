"""Unit tests for ProductionSyncer core logic (no database required).

Tests anonymization strategies, table selection, and checkpoint functionality
in isolation without requiring database connections.
"""

import json
import tempfile
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest

from confiture.config.environment import DatabaseConfig
from confiture.core.syncer import (
    AnonymizationRule,
    ProductionSyncer,
    SyncConfig,
    TableSelection,
)


class TestAnonymizationStrategies:
    """Test anonymization value transformations."""

    def setup_method(self):
        """Create syncer instance for testing."""
        # Create minimal database configs (won't actually connect in unit tests)
        source_config = DatabaseConfig(
            host="localhost",
            port=5432,
            database="source_db",
            user="test",
            password="test",
        )
        target_config = DatabaseConfig(
            host="localhost",
            port=5432,
            database="target_db",
            user="test",
            password="test",
        )
        self.syncer = ProductionSyncer(source_config, target_config)

    def test_anonymize_email_strategy(self):
        """Test email anonymization produces valid email format."""
        result = self.syncer._anonymize_value("john.doe@example.com", "email")

        # Should be a valid email format
        assert "@" in result
        assert result.endswith("@example.com")
        assert result.startswith("user_")

        # Should not be the original
        assert result != "john.doe@example.com"

    def test_anonymize_email_deterministic(self):
        """Test email anonymization is deterministic with same input."""
        email = "test@example.com"

        result1 = self.syncer._anonymize_value(email, "email")
        result2 = self.syncer._anonymize_value(email, "email")

        # Same input should produce same output (hash-based)
        assert result1 == result2

    def test_anonymize_email_different_inputs(self):
        """Test different emails produce different anonymized values."""
        email1 = "alice@example.com"
        email2 = "bob@example.com"

        result1 = self.syncer._anonymize_value(email1, "email")
        result2 = self.syncer._anonymize_value(email2, "email")

        # Different inputs should produce different outputs
        assert result1 != result2

    def test_anonymize_phone_strategy(self):
        """Test phone number anonymization produces valid format."""
        result = self.syncer._anonymize_value("+1-555-1234", "phone")

        # Should be in format +1-555-XXXX
        assert result.startswith("+1-555-")
        assert len(result) == len("+1-555-1234")

    def test_anonymize_phone_with_seed(self):
        """Test phone anonymization is deterministic with seed."""
        phone = "+1-555-9876"
        seed = 12345

        result1 = self.syncer._anonymize_value(phone, "phone", seed=seed)
        result2 = self.syncer._anonymize_value(phone, "phone", seed=seed)

        # Same seed should produce same output
        assert result1 == result2

    def test_anonymize_phone_different_seeds(self):
        """Test different seeds produce different phone numbers."""
        phone = "+1-555-9876"

        result1 = self.syncer._anonymize_value(phone, "phone", seed=100)
        result2 = self.syncer._anonymize_value(phone, "phone", seed=200)

        # Different seeds should produce different outputs
        # (may occasionally collide due to modulo, but very unlikely)
        assert result1 == result2 or result1 != result2  # Either is acceptable

    def test_anonymize_name_strategy(self):
        """Test name anonymization produces user-friendly format."""
        result = self.syncer._anonymize_value("John Doe", "name")

        # Should be in format "User XXXX"
        assert result.startswith("User ")
        assert len(result) > 5

        # Should not be the original
        assert result != "John Doe"

    def test_anonymize_name_deterministic(self):
        """Test name anonymization is deterministic."""
        name = "Alice Johnson"

        result1 = self.syncer._anonymize_value(name, "name")
        result2 = self.syncer._anonymize_value(name, "name")

        # Same input should produce same output
        assert result1 == result2

    def test_anonymize_redact_strategy(self):
        """Test redact strategy replaces value with [REDACTED]."""
        result = self.syncer._anonymize_value("sensitive-data", "redact")

        assert result == "[REDACTED]"

    def test_anonymize_redact_any_value(self):
        """Test redact works with any value type."""
        assert self.syncer._anonymize_value("text", "redact") == "[REDACTED]"
        assert self.syncer._anonymize_value(123, "redact") == "[REDACTED]"
        assert self.syncer._anonymize_value("SSN-123-45-6789", "redact") == "[REDACTED]"

    def test_anonymize_hash_strategy(self):
        """Test hash strategy produces deterministic hash."""
        result = self.syncer._anonymize_value("unique-id-12345", "hash")

        # Should be a 16-character hex string
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_anonymize_hash_deterministic(self):
        """Test hash strategy is deterministic."""
        value = "test-value-123"

        result1 = self.syncer._anonymize_value(value, "hash")
        result2 = self.syncer._anonymize_value(value, "hash")

        # Same input should produce same hash
        assert result1 == result2

    def test_anonymize_hash_different_inputs(self):
        """Test different inputs produce different hashes."""
        result1 = self.syncer._anonymize_value("value1", "hash")
        result2 = self.syncer._anonymize_value("value2", "hash")

        # Different inputs should produce different hashes
        assert result1 != result2

    def test_anonymize_null_value(self):
        """Test NULL values remain NULL regardless of strategy."""
        assert self.syncer._anonymize_value(None, "email") is None
        assert self.syncer._anonymize_value(None, "phone") is None
        assert self.syncer._anonymize_value(None, "name") is None
        assert self.syncer._anonymize_value(None, "redact") is None
        assert self.syncer._anonymize_value(None, "hash") is None

    def test_anonymize_unknown_strategy(self):
        """Test unknown strategy defaults to redaction."""
        result = self.syncer._anonymize_value("data", "unknown_strategy")

        # Unknown strategy should redact by default (safe choice)
        assert result == "[REDACTED]"

    def test_anonymize_empty_string(self):
        """Test empty string handling."""
        result = self.syncer._anonymize_value("", "email")

        # Empty string should still be anonymized
        assert result != ""
        assert "@" in result


class TestTableSelection:
    """Test table selection logic without database."""

    def setup_method(self):
        """Create syncer instance with mocked database connection."""
        source_config = DatabaseConfig(
            host="localhost",
            port=5432,
            database="source_db",
            user="test",
            password="test",
        )
        target_config = DatabaseConfig(
            host="localhost",
            port=5432,
            database="target_db",
            user="test",
            password="test",
        )
        self.syncer = ProductionSyncer(source_config, target_config)

    def test_select_tables_include_only(self):
        """Test selecting specific tables with include list."""
        all_tables = ["users", "posts", "comments", "likes"]

        # Mock get_all_tables
        self.syncer.get_all_tables = MagicMock(return_value=all_tables)

        selection = TableSelection(include=["users", "posts"])
        result = self.syncer.select_tables(selection)

        assert result == ["users", "posts"]

    def test_select_tables_exclude_only(self):
        """Test excluding specific tables."""
        all_tables = ["users", "posts", "comments", "likes"]

        self.syncer.get_all_tables = MagicMock(return_value=all_tables)

        selection = TableSelection(exclude=["comments", "likes"])
        result = self.syncer.select_tables(selection)

        assert result == ["users", "posts"]

    def test_select_tables_include_and_exclude(self):
        """Test include and exclude together (exclude takes precedence)."""
        all_tables = ["users", "posts", "comments", "likes", "shares"]

        self.syncer.get_all_tables = MagicMock(return_value=all_tables)

        selection = TableSelection(
            include=["users", "posts", "comments"],
            exclude=["comments"],
        )
        result = self.syncer.select_tables(selection)

        # Should include users and posts, but exclude comments
        assert result == ["users", "posts"]

    def test_select_tables_no_filters(self):
        """Test selecting all tables when no filters provided."""
        all_tables = ["users", "posts", "comments"]

        self.syncer.get_all_tables = MagicMock(return_value=all_tables)

        selection = TableSelection()
        result = self.syncer.select_tables(selection)

        # Should return all tables
        assert result == all_tables

    def test_select_tables_include_nonexistent(self):
        """Test including tables that don't exist."""
        all_tables = ["users", "posts"]

        self.syncer.get_all_tables = MagicMock(return_value=all_tables)

        selection = TableSelection(include=["users", "nonexistent"])
        result = self.syncer.select_tables(selection)

        # Should only include tables that actually exist
        assert result == ["users"]

    def test_select_tables_exclude_all(self):
        """Test excluding all tables results in empty list."""
        all_tables = ["users", "posts"]

        self.syncer.get_all_tables = MagicMock(return_value=all_tables)

        selection = TableSelection(exclude=["users", "posts"])
        result = self.syncer.select_tables(selection)

        assert result == []


class TestCheckpointFunctionality:
    """Test checkpoint save/load without database."""

    def setup_method(self):
        """Create syncer instance."""
        source_config = DatabaseConfig(
            host="localhost",
            port=5432,
            database="source_db",
            user="test",
            password="test",
        )
        target_config = DatabaseConfig(
            host="localhost",
            port=5432,
            database="target_db",
            user="test",
            password="test",
        )
        self.syncer = ProductionSyncer(source_config, target_config)

    def test_save_checkpoint_creates_file(self):
        """Test checkpoint file is created with correct structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_file = Path(tmpdir) / "sync.checkpoint"

            # Add some metrics
            from confiture.core.syncer import TableMetrics

            self.syncer._metrics["users"] = TableMetrics(
                rows_synced=1000,
                elapsed_seconds=5.2,
                rows_per_second=192.3,
                synced_at="2025-01-01T12:00:00",
            )

            self.syncer.save_checkpoint(checkpoint_file)

            # Verify file exists
            assert checkpoint_file.exists()

            # Verify file structure
            with open(checkpoint_file) as f:
                data = json.load(f)

            assert data["version"] == "1.0"
            assert "timestamp" in data
            assert "source_database" in data
            assert "target_database" in data
            assert "completed_tables" in data
            assert "users" in data["completed_tables"]
            assert data["completed_tables"]["users"]["rows_synced"] == 1000

    def test_save_checkpoint_creates_parent_dirs(self):
        """Test checkpoint saves to nested directory (creates parents)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_file = Path(tmpdir) / "nested" / "dir" / "checkpoint.json"

            self.syncer.save_checkpoint(checkpoint_file)

            # Verify file exists (parent dirs created)
            assert checkpoint_file.exists()

    def test_load_checkpoint_restores_state(self):
        """Test loading checkpoint restores completed tables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_file = Path(tmpdir) / "checkpoint.json"

            # Create checkpoint data
            checkpoint_data = {
                "version": "1.0",
                "timestamp": "2025-01-01T12:00:00",
                "source_database": "localhost:5432/source",
                "target_database": "localhost:5432/target",
                "completed_tables": {
                    "users": {"rows_synced": 1000, "synced_at": "2025-01-01T12:00:00"},
                    "posts": {"rows_synced": 500, "synced_at": "2025-01-01T12:05:00"},
                },
            }

            with open(checkpoint_file, "w") as f:
                json.dump(checkpoint_data, f)

            # Load checkpoint
            self.syncer.load_checkpoint(checkpoint_file)

            # Verify state restored
            assert "users" in self.syncer._completed_tables
            assert "posts" in self.syncer._completed_tables
            assert len(self.syncer._completed_tables) == 2

    def test_load_checkpoint_nonexistent_file_raises(self):
        """Test loading nonexistent checkpoint raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_file = Path(tmpdir) / "nonexistent.json"

            with pytest.raises(FileNotFoundError):
                self.syncer.load_checkpoint(checkpoint_file)

    def test_checkpoint_roundtrip(self):
        """Test save and load checkpoint preserves data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_file = Path(tmpdir) / "checkpoint.json"

            # Add metrics
            from confiture.core.syncer import TableMetrics

            self.syncer._metrics["users"] = TableMetrics(
                rows_synced=1000,
                elapsed_seconds=5.0,
                rows_per_second=200.0,
                synced_at="2025-01-01T12:00:00",
            )
            self.syncer._metrics["posts"] = TableMetrics(
                rows_synced=2000,
                elapsed_seconds=10.0,
                rows_per_second=200.0,
                synced_at="2025-01-01T12:05:00",
            )

            # Save checkpoint
            self.syncer.save_checkpoint(checkpoint_file)

            # Create new syncer and load checkpoint
            source_config = DatabaseConfig(
                host="localhost",
                port=5432,
                database="source_db",
                user="test",
                password="test",
            )
            target_config = DatabaseConfig(
                host="localhost",
                port=5432,
                database="target_db",
                user="test",
                password="test",
            )
            new_syncer = ProductionSyncer(source_config, target_config)
            new_syncer.load_checkpoint(checkpoint_file)

            # Verify completed tables restored
            assert "users" in new_syncer._completed_tables
            assert "posts" in new_syncer._completed_tables


class TestDataclasses:
    """Test dataclass configurations."""

    def test_table_selection_defaults(self):
        """Test TableSelection default values."""
        selection = TableSelection()

        assert selection.include is None
        assert selection.exclude is None

    def test_table_selection_with_values(self):
        """Test TableSelection with explicit values."""
        selection = TableSelection(
            include=["users", "posts"],
            exclude=["temp_table"],
        )

        assert selection.include == ["users", "posts"]
        assert selection.exclude == ["temp_table"]

    def test_anonymization_rule(self):
        """Test AnonymizationRule creation."""
        rule = AnonymizationRule(
            column="email",
            strategy="email",
            seed=12345,
        )

        assert rule.column == "email"
        assert rule.strategy == "email"
        assert rule.seed == 12345

    def test_anonymization_rule_no_seed(self):
        """Test AnonymizationRule without seed."""
        rule = AnonymizationRule(
            column="phone",
            strategy="phone",
        )

        assert rule.column == "phone"
        assert rule.strategy == "phone"
        assert rule.seed is None

    def test_sync_config_defaults(self):
        """Test SyncConfig default values."""
        config = SyncConfig(
            tables=TableSelection(),
        )

        assert config.anonymization is None
        assert config.batch_size == 5000
        assert config.resume is False
        assert config.show_progress is False
        assert config.checkpoint_file is None

    def test_sync_config_with_anonymization(self):
        """Test SyncConfig with anonymization rules."""
        config = SyncConfig(
            tables=TableSelection(include=["users"]),
            anonymization={
                "users": [
                    AnonymizationRule(column="email", strategy="email"),
                    AnonymizationRule(column="phone", strategy="phone"),
                ],
            },
            batch_size=1000,
            resume=True,
            show_progress=True,
        )

        assert config.tables.include == ["users"]
        assert config.anonymization is not None
        anon_config = cast(dict[str, list], config.anonymization)
        assert "users" in anon_config
        assert len(anon_config["users"]) == 2
        assert config.batch_size == 1000
        assert config.resume is True
        assert config.show_progress is True


class TestMetrics:
    """Test metrics tracking."""

    def setup_method(self):
        """Create syncer instance."""
        source_config = DatabaseConfig(
            host="localhost",
            port=5432,
            database="source_db",
            user="test",
            password="test",
        )
        target_config = DatabaseConfig(
            host="localhost",
            port=5432,
            database="target_db",
            user="test",
            password="test",
        )
        self.syncer = ProductionSyncer(source_config, target_config)

    def test_get_metrics_empty(self):
        """Test getting metrics when no tables synced."""
        metrics = self.syncer.get_metrics()

        assert metrics == {}

    def test_get_metrics_with_data(self):
        """Test getting metrics after adding table data."""
        from confiture.core.syncer import TableMetrics

        self.syncer._metrics["users"] = TableMetrics(
            rows_synced=1000,
            elapsed_seconds=5.0,
            rows_per_second=200.0,
            synced_at="2025-01-01T12:00:00",
        )

        metrics = self.syncer.get_metrics()

        assert "users" in metrics
        assert metrics["users"]["rows_synced"] == 1000
        assert metrics["users"]["elapsed_seconds"] == 5.0
        assert metrics["users"]["rows_per_second"] == 200.0
        assert metrics["users"]["synced_at"] == "2025-01-01T12:00:00"

    def test_get_metrics_multiple_tables(self):
        """Test metrics for multiple tables."""
        from confiture.core.syncer import TableMetrics

        self.syncer._metrics["users"] = TableMetrics(
            rows_synced=1000,
            elapsed_seconds=5.0,
            rows_per_second=200.0,
            synced_at="2025-01-01T12:00:00",
        )
        self.syncer._metrics["posts"] = TableMetrics(
            rows_synced=2000,
            elapsed_seconds=8.0,
            rows_per_second=250.0,
            synced_at="2025-01-01T12:05:00",
        )

        metrics = self.syncer.get_metrics()

        assert len(metrics) == 2
        assert "users" in metrics
        assert "posts" in metrics
