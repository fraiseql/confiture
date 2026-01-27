"""
pgGit client for Confiture integration.

Provides a Python interface to pgGit PostgreSQL functions.
This client is designed for development and staging databases only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from confiture.integrations.pggit.detection import require_pggit
from confiture.integrations.pggit.exceptions import (
    PgGitBranchError,
    PgGitCheckoutError,
    PgGitCommitError,
    PgGitMergeConflictError,
)

if TYPE_CHECKING:
    from psycopg import Connection


@dataclass
class Branch:
    """Represents a pgGit branch."""

    name: str
    status: str  # ACTIVE, MERGED, DELETED
    size_mb: Decimal | None = None
    last_commit: datetime | None = None
    days_inactive: int | None = None
    commit_count: int | None = None
    is_current: bool = False


@dataclass
class Commit:
    """Represents a pgGit commit."""

    hash: str
    message: str
    author: str | None = None
    timestamp: datetime | None = None
    branch: str | None = None
    parent_hash: str | None = None


@dataclass
class StatusInfo:
    """pgGit status information."""

    components: dict[str, dict[str, str]] = field(default_factory=dict)
    current_branch: str | None = None
    tracking_enabled: bool = False
    deployment_mode: bool = False


@dataclass
class DiffEntry:
    """Represents a single diff entry between branches/commits."""

    object_type: str  # TABLE, VIEW, FUNCTION, etc.
    object_name: str
    operation: str  # CREATE, ALTER, DROP
    old_ddl: str | None = None
    new_ddl: str | None = None


@dataclass
class MergeResult:
    """Result of a merge operation."""

    success: bool
    message: str
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    merged_objects: int = 0


class PgGitClient:
    """
    Client for interacting with pgGit extension.

    This client wraps pgGit SQL functions and provides a Pythonic
    interface for branch management, commits, merges, and diffs.

    IMPORTANT: This client is for DEVELOPMENT databases only.
    Do not use pgGit on production databases.

    Example:
        >>> with psycopg.connect(DEV_DATABASE_URL) as conn:
        ...     client = PgGitClient(conn)
        ...
        ...     # Create and switch to feature branch
        ...     client.create_branch("feature/payments")
        ...     client.checkout("feature/payments")
        ...
        ...     # Make schema changes directly in SQL
        ...     conn.execute("ALTER TABLE users ADD COLUMN stripe_id TEXT")
        ...
        ...     # View changes
        ...     diff = client.diff("main", "feature/payments")
        ...     for entry in diff:
        ...         print(f"{entry.operation} {entry.object_name}")
        ...
        ...     # Merge back to main
        ...     result = client.merge("feature/payments", "main")
        ...     if result.success:
        ...         print("Merged successfully!")
    """

    def __init__(
        self,
        connection: Connection,
        *,
        auto_init: bool = False,
    ):
        """
        Initialize pgGit client.

        Args:
            connection: Active PostgreSQL connection (psycopg3)
            auto_init: If True, initialize pgGit if not already initialized

        Raises:
            PgGitNotAvailableError: If pgGit extension not installed
            PgGitVersionError: If pgGit version is too old
        """
        self._connection = connection
        self._version = require_pggit(connection)

        if auto_init and not self._is_initialized():
            self.init()

    @property
    def connection(self) -> Connection:
        """Get the underlying database connection."""
        return self._connection

    @property
    def version(self) -> tuple[int, int, int]:
        """Get the pgGit version."""
        return self._version

    # ─────────────────────────────────────────────────────────────────
    # Initialization
    # ─────────────────────────────────────────────────────────────────

    def _is_initialized(self) -> bool:
        """Check if pgGit is initialized."""
        try:
            with self._connection.cursor() as cursor:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'pggit'
                        AND table_name = 'branches'
                    )
                """)
                result = cursor.fetchone()
                return bool(result and result[0])
        except Exception:
            return False

    def init(self) -> None:
        """
        Initialize pgGit in the database.

        Creates the pggit schema and required tables if they don't exist.
        Safe to call multiple times (idempotent).
        """
        # pgGit should auto-initialize on extension creation
        # This is here for manual initialization if needed
        with self._connection.cursor() as cursor:
            cursor.execute("""
                DO $$
                BEGIN
                    -- Ensure main branch exists
                    INSERT INTO pggit.branches (name, status)
                    VALUES ('main', 'ACTIVE')
                    ON CONFLICT (name) DO NOTHING;
                END $$;
            """)
        self._connection.commit()

    # ─────────────────────────────────────────────────────────────────
    # Branch Operations
    # ─────────────────────────────────────────────────────────────────

    def create_branch(
        self,
        name: str,
        from_branch: str = "main",
        *,
        copy_data: bool = False,
    ) -> Branch:
        """
        Create a new branch.

        Args:
            name: Name of the new branch (e.g., "feature/payments")
            from_branch: Branch to create from (default: "main")
            copy_data: Whether to copy data (not just schema)

        Returns:
            The created Branch object

        Raises:
            PgGitBranchError: If branch creation fails

        Example:
            >>> branch = client.create_branch("feature/payments")
            >>> print(f"Created branch: {branch.name}")
        """
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pggit.create_branch(%s, %s, %s)",
                    (name, from_branch, copy_data),
                )
                self._connection.commit()

            return self.get_branch(name)
        except Exception as e:
            self._connection.rollback()
            raise PgGitBranchError(
                f"Failed to create branch '{name}' from '{from_branch}': {e}"
            ) from e

    def delete_branch(self, name: str, *, force: bool = False) -> None:
        """
        Delete a branch.

        Args:
            name: Branch name to delete
            force: Force delete even if not merged

        Raises:
            PgGitBranchError: If branch deletion fails
        """
        if name.lower() in ("main", "master"):
            raise PgGitBranchError("Cannot delete the main branch")

        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pggit.delete_branch(%s, %s)",
                    (name, force),
                )
                self._connection.commit()
        except Exception as e:
            self._connection.rollback()
            raise PgGitBranchError(f"Failed to delete branch '{name}': {e}") from e

    def checkout(self, branch_name: str) -> str:
        """
        Switch to a different branch.

        Args:
            branch_name: Name of branch to switch to

        Returns:
            Message confirming the checkout

        Raises:
            PgGitCheckoutError: If checkout fails
        """
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pggit.checkout_branch(%s)",
                    (branch_name,),
                )
                result = cursor.fetchone()
                self._connection.commit()
                return result[0] if result else f"Switched to {branch_name}"
        except Exception as e:
            self._connection.rollback()
            raise PgGitCheckoutError(f"Failed to checkout branch '{branch_name}': {e}") from e

    def get_current_branch(self) -> str:
        """
        Get the name of the current branch.

        Returns:
            Current branch name (default: "main")
        """
        try:
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('pggit.current_branch', true)")
                result = cursor.fetchone()
                return result[0] if result and result[0] else "main"
        except Exception:
            return "main"

    def get_branch(self, name: str) -> Branch:
        """
        Get branch details.

        Args:
            name: Branch name

        Returns:
            Branch object with details

        Raises:
            PgGitBranchError: If branch doesn't exist
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    name,
                    status::text,
                    created_at
                FROM pggit.branches
                WHERE name = %s
            """,
                (name,),
            )
            result = cursor.fetchone()

            if not result:
                raise PgGitBranchError(f"Branch '{name}' not found")

            current = self.get_current_branch()

            return Branch(
                name=result[0],
                status=result[1],
                is_current=(result[0] == current),
            )

    def list_branches(self, status: str | None = None) -> list[Branch]:
        """
        List all branches.

        Args:
            status: Filter by status (ACTIVE, MERGED, DELETED)

        Returns:
            List of Branch objects
        """
        current = self.get_current_branch()

        with self._connection.cursor() as cursor:
            if status:
                cursor.execute(
                    """
                    SELECT name, status::text, created_at
                    FROM pggit.branches
                    WHERE status = %s::pggit.branch_status
                    ORDER BY created_at DESC
                """,
                    (status,),
                )
            else:
                cursor.execute("""
                    SELECT name, status::text, created_at
                    FROM pggit.branches
                    ORDER BY created_at DESC
                """)

            return [
                Branch(
                    name=row[0],
                    status=row[1],
                    is_current=(row[0] == current),
                )
                for row in cursor.fetchall()
            ]

    # ─────────────────────────────────────────────────────────────────
    # Commit Operations
    # ─────────────────────────────────────────────────────────────────

    def commit(self, message: str, *, author: str | None = None) -> Commit:
        """
        Create a commit with current changes.

        Args:
            message: Commit message
            author: Author name (defaults to database user)

        Returns:
            The created Commit object

        Raises:
            PgGitCommitError: If commit fails
        """
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pggit.create_commit(%s, %s)",
                    (message, author),
                )
                result = cursor.fetchone()
                self._connection.commit()

                commit_hash = result[0] if result else None
                if not commit_hash:
                    raise PgGitCommitError("Commit returned no hash")

                return Commit(
                    hash=commit_hash,
                    message=message,
                    author=author,
                    timestamp=datetime.now(),
                    branch=self.get_current_branch(),
                )
        except PgGitCommitError:
            raise
        except Exception as e:
            self._connection.rollback()
            raise PgGitCommitError(f"Failed to create commit: {e}") from e

    def log(
        self,
        _branch: str | None = None,
        limit: int = 50,
    ) -> list[Commit]:
        """
        Get commit history.

        Args:
            _branch: Filter by branch (default: all branches)
            limit: Maximum number of commits to return

        Returns:
            List of Commit objects (most recent first)
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM pggit.log(%s)
                LIMIT %s
            """,
                (limit, limit),
            )

            return [
                Commit(
                    hash=row[0] if len(row) > 0 else "",
                    message=row[1] if len(row) > 1 else "",
                    author=row[2] if len(row) > 2 else None,
                    timestamp=row[3] if len(row) > 3 else None,
                )
                for row in cursor.fetchall()
            ]

    # ─────────────────────────────────────────────────────────────────
    # Merge Operations
    # ─────────────────────────────────────────────────────────────────

    def merge(
        self,
        source_branch: str,
        target_branch: str = "main",
    ) -> MergeResult:
        """
        Merge source branch into target branch.

        Args:
            source_branch: Branch to merge from
            target_branch: Branch to merge into (default: "main")

        Returns:
            MergeResult with outcome details

        Raises:
            PgGitMergeConflictError: If conflicts need resolution

        Example:
            >>> result = client.merge("feature/payments", "main")
            >>> if result.success:
            ...     print(f"Merged {result.merged_objects} objects")
        """
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pggit.merge_branches(%s, %s)",
                    (source_branch, target_branch),
                )
                result = cursor.fetchone()
                self._connection.commit()

                return MergeResult(
                    success=True,
                    message=result[0] if result else "Merge completed",
                    conflicts=[],
                )
        except Exception as e:
            self._connection.rollback()
            error_str = str(e).lower()

            # Check if it's a conflict error
            if "conflict" in error_str:
                conflicts = self._get_conflicts()
                raise PgGitMergeConflictError(
                    f"Merge conflict between '{source_branch}' and '{target_branch}'",
                    conflicts=conflicts,
                ) from None

            raise PgGitBranchError(f"Merge failed: {e}") from e

    def _get_conflicts(self) -> list[dict[str, Any]]:
        """Get list of unresolved merge conflicts."""
        try:
            with self._connection.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        object_type,
                        object_name,
                        ours,
                        theirs
                    FROM pggit.merge_conflicts
                    WHERE resolved = false
                """)
                return [
                    {
                        "object_type": row[0],
                        "object_name": row[1],
                        "ours": row[2],
                        "theirs": row[3],
                    }
                    for row in cursor.fetchall()
                ]
        except Exception:
            return []

    def resolve_conflict(
        self,
        object_name: str,
        resolution: str,
        *,
        custom_ddl: str | None = None,
    ) -> None:
        """
        Resolve a merge conflict.

        Args:
            object_name: Name of the conflicting object
            resolution: One of 'ours', 'theirs', 'custom'
            custom_ddl: Custom DDL if resolution is 'custom'
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pggit.merge_conflicts
                SET resolved = true,
                    resolution = %s,
                    resolved_ddl = COALESCE(%s,
                        CASE %s
                            WHEN 'ours' THEN ours
                            WHEN 'theirs' THEN theirs
                        END
                    )
                WHERE object_name = %s AND resolved = false
            """,
                (resolution, custom_ddl, resolution, object_name),
            )
            self._connection.commit()

    def abort_merge(self) -> None:
        """Abort an in-progress merge."""
        with self._connection.cursor() as cursor:
            cursor.execute("""
                DELETE FROM pggit.merge_conflicts WHERE resolved = false
            """)
            self._connection.commit()

    # ─────────────────────────────────────────────────────────────────
    # Diff Operations
    # ─────────────────────────────────────────────────────────────────

    def diff(
        self,
        from_ref: str,
        to_ref: str = "HEAD",
    ) -> list[DiffEntry]:
        """
        Get diff between two commits or branches.

        Args:
            from_ref: Starting commit/branch
            to_ref: Ending commit/branch (default: HEAD)

        Returns:
            List of DiffEntry objects describing changes
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM pggit.diff_schemas(%s, %s)
            """,
                (from_ref, to_ref),
            )

            return [
                DiffEntry(
                    object_type=row[0] if len(row) > 0 else "UNKNOWN",
                    object_name=row[1] if len(row) > 1 else "unknown",
                    operation=row[2] if len(row) > 2 else "UNKNOWN",
                    old_ddl=row[3] if len(row) > 3 else None,
                    new_ddl=row[4] if len(row) > 4 else None,
                )
                for row in cursor.fetchall()
            ]

    # ─────────────────────────────────────────────────────────────────
    # Status Operations
    # ─────────────────────────────────────────────────────────────────

    def status(self) -> StatusInfo:
        """
        Get current pgGit status.

        Returns:
            StatusInfo with current state information
        """
        info = StatusInfo()
        info.current_branch = self.get_current_branch()

        with self._connection.cursor() as cursor:
            cursor.execute("SELECT * FROM pggit.status()")
            for row in cursor.fetchall():
                component = row[0] if len(row) > 0 else "unknown"
                status = row[1] if len(row) > 1 else "unknown"
                details = row[2] if len(row) > 2 else ""

                info.components[component] = {
                    "status": status,
                    "details": details,
                }

                if component == "Tracking":
                    info.tracking_enabled = status == "enabled"
                elif component == "Deployment Mode":
                    info.deployment_mode = status == "active"

        return info

    # ─────────────────────────────────────────────────────────────────
    # History Operations
    # ─────────────────────────────────────────────────────────────────

    def get_history(
        self,
        object_name: str,
        object_type: str = "TABLE",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Get version history for a specific object.

        Args:
            object_name: Name of the database object
            object_type: Type of object (TABLE, VIEW, FUNCTION, etc.)
            limit: Maximum history entries to return

        Returns:
            List of history entries
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM pggit.get_history(%s, %s)
                LIMIT %s
            """,
                (object_name, object_type, limit),
            )

            return [
                {
                    "version": row[0] if len(row) > 0 else None,
                    "operation": row[1] if len(row) > 1 else None,
                    "timestamp": row[2] if len(row) > 2 else None,
                    "author": row[3] if len(row) > 3 else None,
                    "ddl": row[4] if len(row) > 4 else None,
                }
                for row in cursor.fetchall()
            ]

    def get_version(self, object_name: str) -> dict[str, Any] | None:
        """
        Get current version info for an object.

        Args:
            object_name: Name of the database object

        Returns:
            Version info dict or None if not tracked
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM pggit.get_version(%s)
            """,
                (object_name,),
            )
            result = cursor.fetchone()

            if not result:
                return None

            return {
                "object_name": result[0] if len(result) > 0 else object_name,
                "version": result[1] if len(result) > 1 else None,
                "version_string": result[2] if len(result) > 2 else None,
            }
