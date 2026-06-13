"""Git integration for schema validation.

Provides git operations needed for pre-commit hooks and CI/CD workflows:
- File retrieval from git refs
- Changed file detection
- Staged file detection
"""

import re
import subprocess
from pathlib import Path

from confiture.exceptions import GitError, NotAGitRepositoryError

# Allows commit hashes, branch names, tags, and common ref formats like
# origin/main, HEAD, HEAD~1, refs/heads/main — but rejects shell metacharacters.
_VALID_GIT_REF_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_.\-~@^{}]*$")


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
                timeout=3,  # local filesystem check; 3s is generous
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

        if not _VALID_GIT_REF_RE.match(ref):
            raise GitError(f"Invalid git reference: {ref!r}")

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

            # Check if file doesn't exist at ref (not found). A file that is
            # new in the working tree but absent from the ref's tree reports
            # "exists on disk, but not in '<ref>'" — also a legitimate "absent
            # at this ref" signal, not an error.
            if (
                "does not exist" in error_msg
                or "not found" in error_msg
                or "but not in" in error_msg
            ):
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

        for ref in (base_ref, target_ref):
            if not _VALID_GIT_REF_RE.match(ref):
                raise GitError(f"Invalid git reference: {ref!r}")

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

    def show_file_at_ref(self, file_path: Path, ref: str) -> str | None:
        """Return file content at the given git ref.

        Args:
            file_path: Relative path to file from repo root
            ref: Git reference (commit hash, branch name, etc.)

        Returns:
            File content as string, or None if the file doesn't exist at that ref

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git command fails for a reason other than missing file
        """
        return self.get_file_at_ref(file_path, ref)

    def get_staged_file_content(self, file_path: Path) -> str | None:
        """Return a file's content from the staging index (``git show :<path>``).

        This is the index blob, which can differ from the working tree when a
        file is staged and then edited further. ``get_file_at_ref`` can't reach
        it: the index is addressed by the bare ``:`` prefix, which
        ``_VALID_GIT_REF_RE`` rejects.

        Args:
            file_path: Relative path to file from repo root

        Returns:
            Staged content as string, or None if the file is not in the index

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git command fails for a reason other than a missing path
        """
        if not self.is_git_repo():
            raise NotAGitRepositoryError(f"Not a git repository: {self.repo_path}")

        index_path = f":{file_path.as_posix()}"
        try:
            result = subprocess.run(
                ["git", "show", index_path],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as e:
            raise GitError(f"Git command timed out retrieving staged '{file_path}'") from e

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            # A path absent from the index reports one of these, depending on
            # whether it also exists in the working tree. Both mean "not staged".
            if (
                "does not exist" in error_msg
                or "not found" in error_msg
                or "but not in the index" in error_msg
            ):
                return None
            raise GitError(f"Git command failed reading staged '{file_path}': {error_msg}")

        return result.stdout

    def get_merge_base(self, base_ref: str, target_ref: str) -> str | None:
        """Return the merge-base commit of two refs (``git merge-base``).

        The merge-base is the common ancestor that three-dot diff semantics
        (``base...target``, used by :meth:`get_changed_files`) compare against.
        Anchoring per-file content diffs here — rather than on the tip of
        ``base_ref`` — keeps the changed-file set and the changed-content set
        consistent when ``base_ref`` has advanced past the fork point.

        Args:
            base_ref: Base git reference
            target_ref: Target git reference

        Returns:
            The merge-base commit hash, or ``base_ref`` itself when the two
            histories share no common ancestor (unrelated histories).

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If either ref is syntactically invalid
        """
        if not self.is_git_repo():
            raise NotAGitRepositoryError(f"Not a git repository: {self.repo_path}")

        for ref in (base_ref, target_ref):
            if not _VALID_GIT_REF_RE.match(ref):
                raise GitError(f"Invalid git reference: {ref!r}")

        try:
            result = subprocess.run(
                ["git", "merge-base", base_ref, target_ref],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as e:
            raise GitError(
                f"Git command timed out finding merge-base of '{base_ref}' and '{target_ref}'"
            ) from e

        if result.returncode != 0 or not result.stdout.strip():
            # No common ancestor (unrelated histories) — fall back to the base
            # tip so the caller still has a usable anchor.
            return base_ref

        return result.stdout.strip()

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
