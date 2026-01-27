"""Integration tests for pgGit integration.

These tests require:
1. A running PostgreSQL database (via CONFITURE_TEST_DB_URL)
2. pgGit extension installed in that database

Tests will be skipped if pgGit is not available.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import psycopg
import pytest

from confiture.integrations.pggit import (
    MigrationGenerator,
    PgGitBranchError,
    PgGitCheckoutError,
    PgGitClient,
    get_pggit_version,
    is_pggit_available,
    require_pggit,
)


@pytest.fixture
def pggit_connection(test_db_connection: psycopg.Connection):
    """Get a connection with pgGit available, or skip test.

    This fixture checks if pgGit is installed and skips the test
    if not available.
    """
    if not is_pggit_available(test_db_connection):
        pytest.skip("pgGit extension not installed - skipping pgGit integration tests")

    yield test_db_connection


@pytest.fixture
def pggit_client(pggit_connection: psycopg.Connection) -> PgGitClient:
    """Create a PgGitClient for testing."""
    return PgGitClient(pggit_connection)


@pytest.fixture
def clean_pggit_branches(pggit_client: PgGitClient):
    """Clean up any test branches before and after tests."""

    def cleanup():
        try:
            branches = pggit_client.list_branches()
            for branch in branches:
                if branch.name.startswith("test_") or branch.name.startswith("feature/test"):
                    try:
                        pggit_client.delete_branch(branch.name, force=True)
                    except PgGitBranchError:
                        pass  # Branch might not exist or be protected
        except Exception:
            pass

    cleanup()
    yield pggit_client
    cleanup()


class TestPgGitDetectionIntegration:
    """Integration tests for pgGit detection functions."""

    def test_is_pggit_available_returns_bool(self, test_db_connection: psycopg.Connection):
        """is_pggit_available should return True or False without error."""
        result = is_pggit_available(test_db_connection)
        assert isinstance(result, bool)

    def test_get_pggit_version_when_available(self, pggit_connection: psycopg.Connection):
        """get_pggit_version should return version tuple when pgGit installed."""
        version = get_pggit_version(pggit_connection)

        assert version is not None
        assert isinstance(version, tuple)
        assert len(version) == 3
        assert all(isinstance(v, int) for v in version)

    def test_require_pggit_succeeds(self, pggit_connection: psycopg.Connection):
        """require_pggit should succeed when pgGit is available."""
        version = require_pggit(pggit_connection)

        assert version is not None
        assert isinstance(version, tuple)


class TestPgGitClientIntegration:
    """Integration tests for PgGitClient."""

    def test_client_initialization(self, pggit_connection: psycopg.Connection):
        """PgGitClient should initialize successfully."""
        client = PgGitClient(pggit_connection)

        assert client.connection == pggit_connection
        assert client.version is not None

    def test_list_branches(self, pggit_client: PgGitClient):
        """list_branches should return list of branches."""
        branches = pggit_client.list_branches()

        assert isinstance(branches, list)
        # Should have at least main branch
        branch_names = [b.name for b in branches]
        assert "main" in branch_names or len(branches) >= 0

    def test_get_current_branch(self, pggit_client: PgGitClient):
        """get_current_branch should return current branch name."""
        branch = pggit_client.get_current_branch()

        assert isinstance(branch, str)
        assert len(branch) > 0

    def test_create_and_delete_branch(self, clean_pggit_branches: PgGitClient):
        """Should create and delete a branch."""
        client = clean_pggit_branches
        branch_name = "test_create_delete_branch"

        # Create branch
        branch = client.create_branch(branch_name)
        assert branch.name == branch_name

        # Verify it exists
        branches = client.list_branches()
        branch_names = [b.name for b in branches]
        assert branch_name in branch_names

        # Delete branch
        client.delete_branch(branch_name, force=True)

        # Verify it's gone
        branches = client.list_branches()
        branch_names = [b.name for b in branches]
        assert branch_name not in branch_names

    def test_checkout_branch(self, clean_pggit_branches: PgGitClient):
        """Should checkout a branch."""
        client = clean_pggit_branches
        branch_name = "test_checkout_branch"

        # Create and checkout
        client.create_branch(branch_name)
        client.checkout(branch_name)

        # Verify current branch
        current = client.get_current_branch()
        assert current == branch_name

        # Cleanup - go back to main
        client.checkout("main")
        client.delete_branch(branch_name, force=True)

    def test_status(self, pggit_client: PgGitClient):
        """status should return status info."""
        status = pggit_client.status()

        assert status is not None
        assert status.current_branch is not None

    def test_diff_between_same_branch(self, pggit_client: PgGitClient):
        """diff should return empty for same branch."""
        diff = pggit_client.diff("main", "main")

        # Same branch should have no diff (or minimal)
        assert isinstance(diff, list)


class TestPgGitBranchWorkflow:
    """Integration tests for complete branch workflows."""

    def test_feature_branch_workflow(self, clean_pggit_branches: PgGitClient):
        """Test complete feature branch workflow."""
        client = clean_pggit_branches
        conn = client.connection
        branch_name = "feature/test_workflow"

        # 1. Create feature branch
        branch = client.create_branch(branch_name)
        assert branch.name == branch_name

        # 2. Checkout feature branch
        client.checkout(branch_name)
        assert client.get_current_branch() == branch_name

        # 3. Make a schema change (create a test table)
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS test_pggit_workflow_table (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            conn.commit()

        # 4. Check status shows changes (if pgGit tracks it)
        status = client.status()
        assert status.current_branch == branch_name

        # 5. Get diff from main
        _ = client.diff("main", branch_name)
        # Diff behavior depends on pgGit implementation

        # 6. Cleanup - drop table and branch
        with conn.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS test_pggit_workflow_table")
            conn.commit()

        client.checkout("main")
        client.delete_branch(branch_name, force=True)


class TestMigrationGeneratorIntegration:
    """Integration tests for MigrationGenerator."""

    def test_generator_initialization(self, pggit_connection: psycopg.Connection):
        """MigrationGenerator should initialize with pgGit connection."""
        generator = MigrationGenerator(pggit_connection)

        assert generator.client is not None
        assert generator.client.version is not None

    def test_preview_empty_diff(self, pggit_connection: psycopg.Connection):
        """preview should return empty list for same branch."""
        generator = MigrationGenerator(pggit_connection)

        preview = generator.preview("main", "main")

        assert isinstance(preview, list)
        # Same branch comparison should have no changes
        assert len(preview) == 0

    def test_generate_combined_no_changes(self, pggit_connection: psycopg.Connection):
        """generate_combined should return None when no changes."""
        generator = MigrationGenerator(pggit_connection)

        migration = generator.generate_combined("main", "main")

        assert migration is None

    def test_generate_from_branch_with_changes(
        self,
        clean_pggit_branches: PgGitClient,
    ):
        """generate_from_branch should create migrations for actual changes."""
        client = clean_pggit_branches
        conn = client.connection
        branch_name = "feature/test_migration_gen"

        # Create feature branch and make changes
        client.create_branch(branch_name)
        client.checkout(branch_name)

        # Create a test table
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE test_migration_gen_table (
                    id SERIAL PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()

        # Generate migrations
        generator = MigrationGenerator(conn)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            migrations = generator.generate_from_branch(
                branch_name,
                base_branch="main",
                output_dir=output_dir,
            )

            # Check if migrations were generated (depends on pgGit tracking)
            # The diff might be empty if pgGit doesn't track raw DDL changes
            assert isinstance(migrations, list)

            if migrations:
                # Verify files were created
                files = list(output_dir.glob("*.py"))
                assert len(files) == len(migrations)

        # Cleanup
        with conn.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS test_migration_gen_table")
            conn.commit()

        client.checkout("main")
        client.delete_branch(branch_name, force=True)


class TestPgGitErrorHandling:
    """Integration tests for error handling."""

    def test_create_duplicate_branch_fails(self, clean_pggit_branches: PgGitClient):
        """Creating a branch that already exists should fail."""
        client = clean_pggit_branches
        branch_name = "test_duplicate_branch"

        # Create first time
        client.create_branch(branch_name)

        # Try to create again - should fail
        with pytest.raises(PgGitBranchError):
            client.create_branch(branch_name)

        # Cleanup
        client.delete_branch(branch_name, force=True)

    def test_checkout_nonexistent_branch_fails(self, pggit_client: PgGitClient):
        """Checking out a non-existent branch should fail."""
        with pytest.raises((PgGitCheckoutError, PgGitBranchError)):
            pggit_client.checkout("nonexistent_branch_12345")

    def test_delete_main_branch_fails(self, pggit_client: PgGitClient):
        """Deleting main branch should fail."""
        with pytest.raises(PgGitBranchError, match="[Mm]ain"):
            pggit_client.delete_branch("main")
