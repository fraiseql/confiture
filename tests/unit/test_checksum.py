"""Tests for checksum computation and verification."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from confiture.core.checksum import (
    ChecksumConfig,
    ChecksumMismatch,
    ChecksumMismatchBehavior,
    ChecksumVerificationError,
    MigrationChecksumVerifier,
    compute_checksum,
    compute_checksum_from_content,
)


class TestComputeChecksum:
    """Tests for checksum computation functions."""

    def test_compute_checksum_file(self, tmp_path):
        """Test checksum computation from file."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def up(): pass")

        checksum = compute_checksum(test_file)

        assert len(checksum) == 64  # SHA-256 hex
        assert checksum.isalnum()

    def test_compute_checksum_deterministic(self, tmp_path):
        """Test same content = same checksum."""
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        content = "same content for both files"
        file1.write_text(content)
        file2.write_text(content)

        assert compute_checksum(file1) == compute_checksum(file2)

    def test_compute_checksum_different_content(self, tmp_path):
        """Test different content = different checksum."""
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text("content version 1")
        file2.write_text("content version 2")

        assert compute_checksum(file1) != compute_checksum(file2)

    def test_compute_checksum_empty_file(self, tmp_path):
        """Test checksum of empty file."""
        empty_file = tmp_path / "empty.py"
        empty_file.write_text("")

        checksum = compute_checksum(empty_file)

        # SHA-256 of empty string
        assert checksum == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_compute_checksum_large_file(self, tmp_path):
        """Test checksum of large file (chunked reading)."""
        large_file = tmp_path / "large.py"
        # Create file larger than chunk size (8192 bytes)
        large_file.write_text("x" * 20000)

        checksum = compute_checksum(large_file)

        assert len(checksum) == 64
        assert checksum.isalnum()

    def test_compute_checksum_binary_content(self, tmp_path):
        """Test checksum of file with binary content."""
        binary_file = tmp_path / "binary.bin"
        binary_file.write_bytes(b"\x00\x01\x02\xff\xfe")

        checksum = compute_checksum(binary_file)

        assert len(checksum) == 64

    def test_compute_checksum_unicode_content(self, tmp_path):
        """Test checksum of file with unicode content."""
        unicode_file = tmp_path / "unicode.py"
        unicode_file.write_text("# 日本語コメント\ndef up(): pass")

        checksum = compute_checksum(unicode_file)

        assert len(checksum) == 64


class TestComputeChecksumFromContent:
    """Tests for compute_checksum_from_content function."""

    def test_from_string(self):
        """Test checksum from string content."""
        checksum = compute_checksum_from_content("test content")

        assert len(checksum) == 64
        assert checksum.isalnum()

    def test_from_bytes(self):
        """Test checksum from bytes content."""
        checksum = compute_checksum_from_content(b"test content")

        assert len(checksum) == 64

    def test_string_and_bytes_same_result(self):
        """Test string and bytes produce same checksum."""
        content = "test content"
        str_checksum = compute_checksum_from_content(content)
        bytes_checksum = compute_checksum_from_content(content.encode("utf-8"))

        assert str_checksum == bytes_checksum

    def test_matches_file_checksum(self, tmp_path):
        """Test content checksum matches file checksum."""
        content = "def up(): pass"
        test_file = tmp_path / "test.py"
        test_file.write_text(content)

        file_checksum = compute_checksum(test_file)
        content_checksum = compute_checksum_from_content(content)

        assert file_checksum == content_checksum


class TestChecksumConfig:
    """Tests for ChecksumConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ChecksumConfig()

        assert config.enabled is True
        assert config.on_mismatch == ChecksumMismatchBehavior.FAIL
        assert config.algorithm == "sha256"

    def test_custom_behavior(self):
        """Test custom mismatch behavior."""
        config = ChecksumConfig(on_mismatch=ChecksumMismatchBehavior.WARN)

        assert config.on_mismatch == ChecksumMismatchBehavior.WARN

    def test_disabled(self):
        """Test disabled configuration."""
        config = ChecksumConfig(enabled=False)

        assert config.enabled is False


class TestChecksumMismatch:
    """Tests for ChecksumMismatch dataclass."""

    def test_creation(self, tmp_path):
        """Test ChecksumMismatch creation."""
        mismatch = ChecksumMismatch(
            version="001",
            name="create_users",
            file_path=tmp_path / "001_create_users.py",
            expected="abc123",
            actual="def456",
        )

        assert mismatch.version == "001"
        assert mismatch.name == "create_users"
        assert mismatch.expected == "abc123"
        assert mismatch.actual == "def456"


class TestChecksumVerificationError:
    """Tests for ChecksumVerificationError exception."""

    def test_error_message(self, tmp_path):
        """Test error message formatting."""
        mismatches = [
            ChecksumMismatch(
                version="001",
                name="create_users",
                file_path=tmp_path / "001_create_users.py",
                expected="abc123",
                actual="def456",
            ),
            ChecksumMismatch(
                version="002",
                name="add_email",
                file_path=tmp_path / "002_add_email.py",
                expected="111222",
                actual="333444",
            ),
        ]

        error = ChecksumVerificationError(mismatches)

        assert "2 migration(s)" in str(error)
        assert "001" in str(error)
        assert "002" in str(error)
        assert error.mismatches == mismatches


class TestMigrationChecksumVerifier:
    """Tests for MigrationChecksumVerifier class."""

    def test_verify_disabled(self, tmp_path):
        """Test verification when disabled."""
        mock_conn = MagicMock()
        config = ChecksumConfig(enabled=False)
        verifier = MigrationChecksumVerifier(mock_conn, config)

        result = verifier.verify_all(tmp_path)

        assert result == []
        # No database queries should be made
        mock_conn.cursor.assert_not_called()

    def test_verify_no_stored_checksums(self, tmp_path):
        """Test verification with no stored checksums."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        verifier = MigrationChecksumVerifier(mock_conn)
        result = verifier.verify_all(tmp_path)

        assert result == []

    def test_verify_null_checksum_is_mismatch(self, tmp_path):
        """Test that migrations with null checksum are treated as mismatch."""
        # Create migration file
        migration_file = tmp_path / "001_create_users.py"
        migration_file.write_text("def up(): pass")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        # Migration with null checksum
        mock_cursor.fetchall.return_value = [
            ("001", "create_users", None),  # null checksum = mismatch
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        config = ChecksumConfig(on_mismatch=ChecksumMismatchBehavior.IGNORE)
        verifier = MigrationChecksumVerifier(mock_conn, config)
        result = verifier.verify_all(tmp_path)

        # Null checksum should be reported as mismatch
        assert len(result) == 1
        assert result[0].version == "001"
        assert result[0].expected is None

    def test_verify_match(self, tmp_path):
        """Test verification when checksums match."""
        # Create migration file
        migration_file = tmp_path / "001_create_users.py"
        migration_file.write_text("def up(): pass")
        checksum = compute_checksum(migration_file)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("001", "create_users", checksum),
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        verifier = MigrationChecksumVerifier(mock_conn)
        result = verifier.verify_all(tmp_path)

        assert result == []

    def test_verify_mismatch_fail(self, tmp_path):
        """Test verification raises on mismatch with FAIL behavior."""
        # Create migration file
        migration_file = tmp_path / "001_create_users.py"
        migration_file.write_text("def up(): pass")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("001", "create_users", "wrong_checksum"),
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        config = ChecksumConfig(on_mismatch=ChecksumMismatchBehavior.FAIL)
        verifier = MigrationChecksumVerifier(mock_conn, config)

        with pytest.raises(ChecksumVerificationError) as exc_info:
            verifier.verify_all(tmp_path)

        assert len(exc_info.value.mismatches) == 1
        assert exc_info.value.mismatches[0].version == "001"

    def test_verify_mismatch_warn(self, tmp_path, caplog):
        """Test verification logs warning on mismatch with WARN behavior."""
        import logging

        # Create migration file
        migration_file = tmp_path / "001_create_users.py"
        migration_file.write_text("def up(): pass")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("001", "create_users", "wrong_checksum"),
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        config = ChecksumConfig(on_mismatch=ChecksumMismatchBehavior.WARN)
        verifier = MigrationChecksumVerifier(mock_conn, config)

        with caplog.at_level(logging.WARNING):
            result = verifier.verify_all(tmp_path)

        assert len(result) == 1
        assert "modified migrations" in caplog.text

    def test_verify_mismatch_ignore(self, tmp_path):
        """Test verification ignores mismatch with IGNORE behavior."""
        # Create migration file
        migration_file = tmp_path / "001_create_users.py"
        migration_file.write_text("def up(): pass")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("001", "create_users", "wrong_checksum"),
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        config = ChecksumConfig(on_mismatch=ChecksumMismatchBehavior.IGNORE)
        verifier = MigrationChecksumVerifier(mock_conn, config)

        result = verifier.verify_all(tmp_path)

        # Returns mismatches but doesn't raise or log
        assert len(result) == 1

    def test_verify_missing_file(self, tmp_path, caplog):
        """Test verification handles missing files gracefully."""
        import logging

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("001", "create_users", "some_checksum"),  # File doesn't exist
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        verifier = MigrationChecksumVerifier(mock_conn)

        with caplog.at_level(logging.WARNING):
            result = verifier.verify_all(tmp_path)

        assert result == []
        assert "not found" in caplog.text

    def test_verify_single_match(self, tmp_path):
        """Test single file verification when match."""
        migration_file = tmp_path / "001_create_users.py"
        migration_file.write_text("def up(): pass")
        checksum = compute_checksum(migration_file)

        mock_conn = MagicMock()
        verifier = MigrationChecksumVerifier(mock_conn)

        result = verifier.verify_single(migration_file, checksum)

        assert result is True

    def test_verify_single_mismatch(self, tmp_path):
        """Test single file verification when mismatch."""
        migration_file = tmp_path / "001_create_users.py"
        migration_file.write_text("def up(): pass")

        mock_conn = MagicMock()
        verifier = MigrationChecksumVerifier(mock_conn)

        result = verifier.verify_single(migration_file, "wrong_checksum")

        assert result is False

    def test_verify_single_disabled(self, tmp_path):
        """Test single file verification when disabled."""
        migration_file = tmp_path / "001_create_users.py"
        migration_file.write_text("def up(): pass")

        mock_conn = MagicMock()
        config = ChecksumConfig(enabled=False)
        verifier = MigrationChecksumVerifier(mock_conn, config)

        result = verifier.verify_single(migration_file, "any_checksum")

        assert result is True  # Always passes when disabled

    def test_find_migration_file_exact_match(self, tmp_path):
        """Test finding migration file with exact name."""
        migration_file = tmp_path / "001_create_users.py"
        migration_file.write_text("def up(): pass")

        mock_conn = MagicMock()
        verifier = MigrationChecksumVerifier(mock_conn)

        result = verifier._find_migration_file(tmp_path, "001", "create_users")

        assert result == migration_file

    def test_find_migration_file_pattern_match(self, tmp_path):
        """Test finding migration file with pattern match."""
        migration_file = tmp_path / "001_create_users_table.py"
        migration_file.write_text("def up(): pass")

        mock_conn = MagicMock()
        verifier = MigrationChecksumVerifier(mock_conn)

        result = verifier._find_migration_file(tmp_path, "001", "different_name")

        # Should find by pattern (001_*.py)
        assert result == migration_file

    def test_find_migration_file_not_found(self, tmp_path):
        """Test finding migration file when not exists."""
        mock_conn = MagicMock()
        verifier = MigrationChecksumVerifier(mock_conn)

        result = verifier._find_migration_file(tmp_path, "001", "create_users")

        assert result is None

    def test_update_checksum(self, tmp_path):
        """Test updating a single checksum."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        verifier = MigrationChecksumVerifier(mock_conn)
        verifier.update_checksum("001", "new_checksum")

        # Check UPDATE was executed
        mock_cursor.execute.assert_called()
        call_args = mock_cursor.execute.call_args
        assert "UPDATE" in call_args[0][0]
        assert "new_checksum" in call_args[0][1]
        mock_conn.commit.assert_called()

    def test_update_all_checksums(self, tmp_path):
        """Test updating all checksums."""
        # Create migration files
        (tmp_path / "001_create_users.py").write_text("def up(): pass")
        (tmp_path / "002_add_email.py").write_text("def up(): add_email()")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("001", "create_users", "old_checksum1"),
            ("002", "add_email", "old_checksum2"),
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        verifier = MigrationChecksumVerifier(mock_conn)
        updated = verifier.update_all_checksums(tmp_path)

        assert updated == 2


class TestChecksumMismatchBehavior:
    """Tests for ChecksumMismatchBehavior enum."""

    def test_values(self):
        """Test enum values."""
        assert ChecksumMismatchBehavior.FAIL.value == "fail"
        assert ChecksumMismatchBehavior.WARN.value == "warn"
        assert ChecksumMismatchBehavior.IGNORE.value == "ignore"

    def test_from_string(self):
        """Test creating enum from string."""
        assert ChecksumMismatchBehavior("fail") == ChecksumMismatchBehavior.FAIL
        assert ChecksumMismatchBehavior("warn") == ChecksumMismatchBehavior.WARN
        assert ChecksumMismatchBehavior("ignore") == ChecksumMismatchBehavior.IGNORE
