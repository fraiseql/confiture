"""
pgGit-specific exceptions.

All pgGit exceptions inherit from PgGitError, which itself inherits
from ConfiturError, allowing unified exception handling.
"""

from __future__ import annotations

from typing import Any

from confiture.exceptions import ConfiturError


class PgGitError(ConfiturError):
    """
    Base exception for pgGit integration errors.

    All pgGit-related exceptions inherit from this class.
    """

    pass


class PgGitNotAvailableError(PgGitError):
    """
    Raised when pgGit extension is not installed.

    This typically means:
    - The pgGit extension hasn't been created in this database
    - You're connecting to a production database (which shouldn't have pgGit)
    - The extension installation failed

    Resolution:
        CREATE EXTENSION pggit CASCADE;
    """

    pass


class PgGitVersionError(PgGitError):
    """
    Raised when pgGit version is incompatible.

    This means the installed pgGit version is older than the minimum
    required version for this Confiture integration.

    Resolution:
        Update pgGit to the latest version.
    """

    pass


class PgGitBranchError(PgGitError):
    """
    Raised when a branch operation fails.

    Common causes:
    - Branch doesn't exist
    - Branch name is invalid
    - Branch is protected (for deletion)
    - Branch operation conflicted with another operation
    """

    pass


class PgGitMergeConflictError(PgGitError):
    """
    Raised when a merge has conflicts that need resolution.

    The `conflicts` attribute contains details about each conflict,
    including:
    - object_type: TABLE, VIEW, FUNCTION, etc.
    - object_name: Name of the conflicting object
    - ours: Our version of the DDL
    - theirs: Their version of the DDL

    Resolution:
        Use PgGitClient.resolve_conflict() for each conflict, or
        use PgGitClient.abort_merge() to cancel the merge.
    """

    def __init__(self, message: str, conflicts: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.conflicts = conflicts or []

    def __str__(self) -> str:
        base = super().__str__()
        if self.conflicts:
            conflict_summary = ", ".join(
                f"{c.get('object_type', 'UNKNOWN')}:{c.get('object_name', 'unknown')}"
                for c in self.conflicts[:5]
            )
            if len(self.conflicts) > 5:
                conflict_summary += f" (+{len(self.conflicts) - 5} more)"
            return f"{base} [{conflict_summary}]"
        return base


class PgGitCommitError(PgGitError):
    """
    Raised when a commit operation fails.

    Common causes:
    - No changes to commit
    - Commit message is empty
    - Database transaction failed
    """

    pass


class PgGitCheckoutError(PgGitError):
    """
    Raised when checkout fails.

    Common causes:
    - Target branch/commit doesn't exist
    - Uncommitted changes would be lost
    - Database state inconsistent
    """

    pass
