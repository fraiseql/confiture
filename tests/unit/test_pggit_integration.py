"""Unit tests for pgGit integration module.

Tests for pgGit detection, configuration, exceptions, and client classes.
These tests do NOT require an actual PostgreSQL database with pgGit installed.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from confiture.config.environment import PgGitConfig
from confiture.integrations.pggit import (
    MIN_PGGIT_VERSION,
    PgGitBranchError,
    PgGitClient,
    PgGitError,
    PgGitMergeConflictError,
    PgGitNotAvailableError,
    PgGitVersionError,
    get_pggit_version,
    is_pggit_available,
    require_pggit,
)
from confiture.integrations.pggit.client import Branch, Commit, DiffEntry, MergeResult, StatusInfo
from confiture.integrations.pggit.detection import get_pggit_info, is_pggit_initialized


class TestPgGitExceptions:
    """Test pgGit exception hierarchy."""

    def test_pggit_error_inherits_from_confiture_error(self):
        """PgGitError should inherit from ConfiturError."""
        from confiture.exceptions import ConfiturError

        error = PgGitError("test error")
        assert isinstance(error, ConfiturError)

    def test_pggit_not_available_error(self):
        """PgGitNotAvailableError should be a PgGitError."""
        error = PgGitNotAvailableError("pgGit not installed")
        assert isinstance(error, PgGitError)
        assert "not installed" in str(error)

    def test_pggit_version_error(self):
        """PgGitVersionError should be a PgGitError."""
        error = PgGitVersionError("version too old")
        assert isinstance(error, PgGitError)
        assert "version" in str(error)

    def test_pggit_branch_error(self):
        """PgGitBranchError should be a PgGitError."""
        error = PgGitBranchError("branch not found")
        assert isinstance(error, PgGitError)

    def test_pggit_merge_conflict_error_with_conflicts(self):
        """PgGitMergeConflictError should store and display conflicts."""
        conflicts = [
            {"object_type": "TABLE", "object_name": "users"},
            {"object_type": "VIEW", "object_name": "active_users"},
        ]
        error = PgGitMergeConflictError("Merge conflict detected", conflicts=conflicts)

        assert error.conflicts == conflicts
        assert "TABLE:users" in str(error)
        assert "VIEW:active_users" in str(error)

    def test_pggit_merge_conflict_error_truncates_many_conflicts(self):
        """PgGitMergeConflictError should truncate display for many conflicts."""
        conflicts = [{"object_type": f"TABLE", "object_name": f"table_{i}"} for i in range(10)]
        error = PgGitMergeConflictError("Many conflicts", conflicts=conflicts)

        # Should show first 5 and indicate more
        assert "+5 more" in str(error)


class TestPgGitConfig:
    """Test PgGitConfig Pydantic model."""

    def test_default_config(self):
        """PgGitConfig should have sensible defaults."""
        config = PgGitConfig()

        assert config.enabled is False
        assert config.auto_init is True
        assert config.default_branch == "main"
        assert config.auto_commit is False
        assert config.require_branch is False
        assert "main" in config.protected_branches
        assert "master" in config.protected_branches

    def test_config_with_custom_values(self):
        """PgGitConfig should accept custom values."""
        config = PgGitConfig(
            enabled=True,
            default_branch="development",
            auto_commit=True,
            protected_branches=["main", "release"],
        )

        assert config.enabled is True
        assert config.default_branch == "development"
        assert config.auto_commit is True
        assert config.protected_branches == ["main", "release"]

    def test_commit_message_template(self):
        """PgGitConfig should have configurable commit message template."""
        config = PgGitConfig(commit_message_template="[AUTO] {migration_name}")

        assert config.commit_message_template == "[AUTO] {migration_name}"


class TestPgGitDetection:
    """Test pgGit detection functions."""

    def test_is_pggit_available_when_installed(self):
        """is_pggit_available should return True when extension exists."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = (True,)

        result = is_pggit_available(mock_conn)

        assert result is True
        mock_cursor.execute.assert_called_once()

    def test_is_pggit_available_when_not_installed(self):
        """is_pggit_available should return False when extension missing."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = (False,)

        result = is_pggit_available(mock_conn)

        assert result is False

    def test_is_pggit_available_on_exception(self):
        """is_pggit_available should return False on database error."""
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("Connection error")

        result = is_pggit_available(mock_conn)

        assert result is False

    def test_get_pggit_version_parses_version_string(self):
        """get_pggit_version should parse version from pggit.version()."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # First call for is_pggit_available, second for version
        mock_cursor.fetchone.side_effect = [(True,), ("0.1.5",)]

        with patch(
            "confiture.integrations.pggit.detection.is_pggit_available", return_value=True
        ):
            result = get_pggit_version(mock_conn)

        assert result == (0, 1, 5)

    def test_get_pggit_version_returns_none_when_not_available(self):
        """get_pggit_version should return None when pgGit not installed."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.detection.is_pggit_available", return_value=False
        ):
            result = get_pggit_version(mock_conn)

        assert result is None

    def test_require_pggit_raises_when_not_available(self):
        """require_pggit should raise PgGitNotAvailableError when missing."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.detection.is_pggit_available", return_value=False
        ):
            with pytest.raises(PgGitNotAvailableError, match="not installed"):
                require_pggit(mock_conn)

    def test_require_pggit_raises_on_version_mismatch(self):
        """require_pggit should raise PgGitVersionError when version too old."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.detection.is_pggit_available", return_value=True
        ):
            with patch(
                "confiture.integrations.pggit.detection.get_pggit_version",
                return_value=(0, 0, 1),
            ):
                with pytest.raises(PgGitVersionError, match="too old"):
                    require_pggit(mock_conn, min_version=(0, 1, 0))

    def test_require_pggit_returns_version_when_satisfied(self):
        """require_pggit should return version tuple when requirements met."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.detection.is_pggit_available", return_value=True
        ):
            with patch(
                "confiture.integrations.pggit.detection.get_pggit_version",
                return_value=(0, 2, 0),
            ):
                result = require_pggit(mock_conn, min_version=(0, 1, 0))

        assert result == (0, 2, 0)

    def test_min_pggit_version_constant(self):
        """MIN_PGGIT_VERSION should be a valid version tuple."""
        assert isinstance(MIN_PGGIT_VERSION, tuple)
        assert len(MIN_PGGIT_VERSION) == 3
        assert all(isinstance(x, int) for x in MIN_PGGIT_VERSION)


class TestPgGitClientDataclasses:
    """Test pgGit client dataclasses."""

    def test_branch_dataclass(self):
        """Branch dataclass should store branch information."""
        branch = Branch(
            name="feature/test",
            status="ACTIVE",
            commit_count=5,
        )

        assert branch.name == "feature/test"
        assert branch.status == "ACTIVE"
        assert branch.commit_count == 5

    def test_branch_dataclass_with_all_fields(self):
        """Branch dataclass should support all optional fields."""
        from decimal import Decimal

        branch = Branch(
            name="feature/test",
            status="ACTIVE",
            size_mb=Decimal("10.5"),
            last_commit=datetime(2025, 1, 15, 10, 30),
            days_inactive=5,
            commit_count=10,
            is_current=True,
        )

        assert branch.name == "feature/test"
        assert branch.size_mb == Decimal("10.5")
        assert branch.is_current is True

    def test_commit_dataclass(self):
        """Commit dataclass should store commit information."""
        commit = Commit(
            hash="abc123def456",
            message="Add users table",
            author="developer@example.com",
            timestamp=datetime(2025, 1, 15, 11, 0),
        )

        assert commit.hash == "abc123def456"
        assert commit.message == "Add users table"
        assert commit.author == "developer@example.com"

    def test_status_info_dataclass(self):
        """StatusInfo should store pgGit status information."""
        status = StatusInfo(
            current_branch="main",
            tracking_enabled=True,
            deployment_mode=False,
        )

        assert status.current_branch == "main"
        assert status.tracking_enabled is True
        assert status.deployment_mode is False

    def test_status_info_with_components(self):
        """StatusInfo should store component status."""
        status = StatusInfo(
            components={
                "Tracking": {"status": "enabled", "details": ""},
                "Deployment Mode": {"status": "inactive", "details": ""},
            },
            current_branch="main",
        )

        assert "Tracking" in status.components
        assert status.components["Tracking"]["status"] == "enabled"

    def test_diff_entry_dataclass(self):
        """DiffEntry should store diff information."""
        entry = DiffEntry(
            object_type="FUNCTION",
            object_name="calculate_total",
            operation="ALTER",
            old_ddl="CREATE FUNCTION...",
            new_ddl="CREATE OR REPLACE FUNCTION...",
        )

        assert entry.object_type == "FUNCTION"
        assert entry.object_name == "calculate_total"
        assert entry.operation == "ALTER"

    def test_merge_result_success(self):
        """MergeResult should represent successful merge."""
        result = MergeResult(
            success=True,
            message="Merged successfully",
            merged_objects=5,
        )

        assert result.success is True
        assert result.merged_objects == 5
        assert result.conflicts == []

    def test_merge_result_with_conflicts(self):
        """MergeResult should store conflict information."""
        conflicts = [{"object_type": "TABLE", "object_name": "users"}]
        result = MergeResult(
            success=False,
            message="Conflicts detected",
            conflicts=conflicts,
        )

        assert result.success is False
        assert len(result.conflicts) == 1


class TestPgGitClientMocked:
    """Test PgGitClient with mocked database connection."""

    def test_client_initialization(self):
        """PgGitClient should initialize with connection."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.client.require_pggit",
            return_value=(0, 1, 0),
        ):
            client = PgGitClient(mock_conn)

        assert client.connection == mock_conn
        assert client.version == (0, 1, 0)

    def test_client_raises_when_pggit_not_available(self):
        """PgGitClient should raise on initialization if pgGit unavailable."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.client.require_pggit",
            side_effect=PgGitNotAvailableError("Not installed"),
        ):
            with pytest.raises(PgGitNotAvailableError):
                PgGitClient(mock_conn)

    def test_list_branches(self):
        """list_branches should return list of Branch objects."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # Mock branch data
        mock_cursor.fetchall.return_value = [
            ("main", datetime(2025, 1, 1), 10),
            ("feature/test", datetime(2025, 1, 15), 3),
        ]

        with patch(
            "confiture.integrations.pggit.client.require_pggit",
            return_value=(0, 1, 0),
        ):
            client = PgGitClient(mock_conn)
            branches = client.list_branches()

        assert len(branches) == 2
        assert branches[0].name == "main"
        assert branches[1].name == "feature/test"

    def test_create_branch(self):
        """create_branch should create and return new Branch."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # Mock get_branch call after creation
        mock_cursor.fetchone.return_value = ("feature/new", "ACTIVE", None)

        with patch(
            "confiture.integrations.pggit.client.require_pggit",
            return_value=(0, 1, 0),
        ):
            client = PgGitClient(mock_conn)
            branch = client.create_branch("feature/new", from_branch="main")

        assert branch.name == "feature/new"
        mock_cursor.execute.assert_called()

    def test_checkout_branch(self):
        """checkout should switch to specified branch."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "confiture.integrations.pggit.client.require_pggit",
            return_value=(0, 1, 0),
        ):
            client = PgGitClient(mock_conn)
            client.checkout("feature/test")

        # Verify checkout was called
        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        assert any("checkout" in call.lower() for call in calls)

    def test_commit_creates_commit(self):
        """commit should create a new commit with message."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # Mock commit hash return
        mock_cursor.fetchone.return_value = ("commit_hash_123",)

        with patch(
            "confiture.integrations.pggit.client.require_pggit",
            return_value=(0, 1, 0),
        ):
            client = PgGitClient(mock_conn)
            commit = client.commit("Add new table")

        assert commit.message == "Add new table"
        assert commit.hash == "commit_hash_123"


class TestPgGitInfoFunction:
    """Test get_pggit_info diagnostic function."""

    def test_get_pggit_info_when_available(self):
        """get_pggit_info should return comprehensive info dict."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # Mock table list and function count
        mock_cursor.fetchall.return_value = [("objects",), ("branches",)]
        mock_cursor.fetchone.return_value = (42,)

        with patch(
            "confiture.integrations.pggit.detection.is_pggit_available", return_value=True
        ):
            with patch(
                "confiture.integrations.pggit.detection.get_pggit_version",
                return_value=(0, 1, 2),
            ):
                with patch(
                    "confiture.integrations.pggit.detection.is_pggit_initialized",
                    return_value=True,
                ):
                    info = get_pggit_info(mock_conn)

        assert info is not None
        assert info["available"] is True
        assert info["version"] == (0, 1, 2)
        assert info["version_string"] == "0.1.2"
        assert info["initialized"] is True

    def test_get_pggit_info_when_not_available(self):
        """get_pggit_info should return None when pgGit not installed."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.detection.is_pggit_available", return_value=False
        ):
            info = get_pggit_info(mock_conn)

        assert info is None


class TestPgGitInitialized:
    """Test is_pggit_initialized function."""

    def test_is_pggit_initialized_when_tables_exist(self):
        """is_pggit_initialized should return True when core tables exist."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = (True,)

        with patch(
            "confiture.integrations.pggit.detection.is_pggit_available", return_value=True
        ):
            result = is_pggit_initialized(mock_conn)

        assert result is True

    def test_is_pggit_initialized_when_not_available(self):
        """is_pggit_initialized should return False when pgGit not installed."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.detection.is_pggit_available", return_value=False
        ):
            result = is_pggit_initialized(mock_conn)

        assert result is False
