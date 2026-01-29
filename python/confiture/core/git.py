"""Git integration for schema validation.

Provides git operations needed for pre-commit hooks and CI/CD workflows:
- File retrieval from git refs
- Changed file detection
- Staged file detection
"""

import subprocess
from pathlib import Path

from confiture.exceptions import GitError, NotAGitRepositoryError


class GitRepository:
    """Interface to git repository operations via subprocess.

    Uses subprocess to call git commands for all operations.
    No external dependencies required.

    Attributes:
        repo_path: Root directory of git repository

    Example:
        >>> repo = GitRepository(Path("."))
        >>> if repo.is_git_repo():
        ...     content = repo.get_file_at_ref(Path("schema.sql"), "HEAD")
    """

    def __init__(self, repo_path: Path | None = None):
        """Initialize GitRepository with optional repo path.

        Args:
            repo_path: Root directory of git repository.
                      If None, uses current directory.
        """
        self.repo_path = repo_path or Path.cwd()

    def is_git_repo(self) -> bool:
        """Check if directory is a git repository.

        Returns:
            True if .git directory exists, False otherwise.
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0

    def get_file_at_ref(self, file_path: Path, ref: str) -> str | None:
        """Retrieve file content from a git ref.

        Args:
            file_path: Relative path to file from repo root
            ref: Git reference (commit hash, branch name, tag, etc.)

        Returns:
            File content as string, or None if file doesn't exist at ref

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git command fails (invalid ref, etc.)

        Example:
            >>> repo = GitRepository(Path("."))
            >>> content = repo.get_file_at_ref(Path("db/schema/users.sql"), "HEAD")
            >>> content = repo.get_file_at_ref(Path("db/schema/users.sql"), "origin/main")
        """
        if not self.is_git_repo():
            raise NotAGitRepositoryError(f"Not a git repository: {self.repo_path}")

        # Convert Path to forward slashes for git show command
        file_path_str = file_path.as_posix()
        git_ref_path = f"{ref}:{file_path_str}"

        try:
            result = subprocess.run(
                ["git", "show", git_ref_path],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as e:
            raise GitError(f"Git command timed out retrieving '{file_path}' from '{ref}'") from e

        if result.returncode != 0:
            error_msg = result.stderr.strip()

            # Check if file doesn't exist at ref (not found)
            if "does not exist" in error_msg or "not found" in error_msg:
                return None

            # Check if ref doesn't exist
            if "bad revision" in error_msg or "unknown revision" in error_msg:
                raise GitError(f"Invalid git reference '{ref}': {error_msg}")

            # Generic git error
            raise GitError(f"Git command failed: {error_msg}")

        return result.stdout

    def get_changed_files(self, base_ref: str, target_ref: str = "HEAD") -> list[Path]:
        """Get list of files changed between two refs.

        Args:
            base_ref: Base git reference (e.g., "origin/main")
            target_ref: Target git reference (default "HEAD")

        Returns:
            List of file paths (relative to repo root) that changed

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git command fails

        Example:
            >>> repo = GitRepository(Path("."))
            >>> files = repo.get_changed_files("origin/main", "HEAD")
            >>> for f in files:
            ...     print(f)
            db/schema/users.sql
            db/migrations/001_add_users.up.sql
        """
        if not self.is_git_repo():
            raise NotAGitRepositoryError(f"Not a git repository: {self.repo_path}")

        # Get list of changed files (both added and modified)
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", f"{base_ref}...{target_ref}"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as e:
            raise GitError(f"Git command timed out comparing '{base_ref}' to '{target_ref}'") from e

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            if "bad revision" in error_msg or "unknown revision" in error_msg:
                raise GitError(f"Invalid git reference: {error_msg}")
            raise GitError(f"Git command failed: {error_msg}")

        if not result.stdout.strip():
            return []

        # Convert to Path objects
        return [Path(line) for line in result.stdout.strip().split("\n")]

    def get_staged_files(self) -> list[Path]:
        """Get list of currently staged files.

        Returns:
            List of file paths (relative to repo root) that are staged

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git command fails

        Example:
            >>> repo = GitRepository(Path("."))
            >>> files = repo.get_staged_files()
            >>> for f in files:
            ...     print(f)
            db/schema/users.sql
        """
        if not self.is_git_repo():
            raise NotAGitRepositoryError(f"Not a git repository: {self.repo_path}")

        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as e:
            raise GitError("Git command timed out getting staged files") from e

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            raise GitError(f"Git command failed: {error_msg}")

        if not result.stdout.strip():
            return []

        return [Path(line) for line in result.stdout.strip().split("\n")]
