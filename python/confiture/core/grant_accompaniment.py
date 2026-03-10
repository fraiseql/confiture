"""Grant accompaniment validation.

Validates that changes to grant files (db/7_grant/) are accompanied by
migration files. Build environments apply grants from the grant directory
automatically; migrate environments (staging, production) only apply grants
when they appear in a migration file. This asymmetry causes silent permission
failures in production when grant files are changed without a migration.
"""

from pathlib import Path

from confiture.core.git import GitRepository
from confiture.models.git import GrantAccompanimentReport


class GrantAccompanimentChecker:
    """Check if grant file changes are accompanied by migration files.

    Unlike MigrationAccompanimentChecker (semantic DDL diff), this uses
    file-level detection: if any file under grant_dir changed, at least
    one .up.sql migration must also be present in the changeset.

    Attributes:
        repo_path: Repository root directory
        git_repo: GitRepository instance
        grant_dir: Relative path to grant directory (default: "db/7_grant")
        migrations_dir: Relative path to migrations directory (default: "db/migrations")

    Example:
        >>> checker = GrantAccompanimentChecker()
        >>> report = checker.check_accompaniment(staged_only=True)
        >>> if not report.is_valid:
        ...     print(f"Error: {report.summary()}")
    """

    def __init__(
        self,
        repo_path: Path | None = None,
        grant_dir: str = "db/7_grant",
        migrations_dir: str = "db/migrations",
    ):
        """Initialize grant accompaniment checker.

        Args:
            repo_path: Repository root directory (default: current directory)
            grant_dir: Relative path to grant directory (default: "db/7_grant")
            migrations_dir: Relative path to migrations directory (default: "db/migrations")
        """
        self.repo_path = repo_path or Path.cwd()
        self.git_repo = GitRepository(self.repo_path)
        self.grant_dir = grant_dir
        self.migrations_dir = migrations_dir

    def check_accompaniment(
        self,
        base_ref: str = "HEAD",
        target_ref: str = "HEAD",
        staged_only: bool = False,
    ) -> GrantAccompanimentReport:
        """Check if grant changes are accompanied by migrations.

        When staged_only=True, uses git diff --cached (actual staged files).
        Otherwise, uses git diff base_ref...target_ref (changed between refs).

        Args:
            base_ref: Base git reference (used when staged_only=False)
            target_ref: Target git reference (used when staged_only=False)
            staged_only: If True, check staged files only (pre-commit mode)

        Returns:
            GrantAccompanimentReport with validation results

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git operations fail
        """
        if staged_only:
            changed_files = self.git_repo.get_staged_files()
        else:
            changed_files = self.git_repo.get_changed_files(base_ref, target_ref)

        grant_files = self._filter_grant_files(changed_files)
        migration_files = self._filter_migration_files(changed_files)

        return GrantAccompanimentReport(
            has_grant_changes=len(grant_files) > 0,
            has_migration_changes=len(migration_files) > 0,
            grant_files_changed=grant_files,
            migration_files_staged=migration_files,
        )

    def _filter_grant_files(self, files: list[Path]) -> list[Path]:
        """Filter to files under grant_dir.

        Args:
            files: List of file paths to filter

        Returns:
            Files that are under the grant directory
        """
        grant_parts = Path(self.grant_dir).parts
        result = []
        for f in files:
            # Check if file path starts with the grant_dir parts
            if f.parts[: len(grant_parts)] == grant_parts:
                result.append(f)
        return result

    def _filter_migration_files(self, files: list[Path]) -> list[Path]:
        """Filter to .up.sql files under migrations_dir.

        Args:
            files: List of file paths to filter

        Returns:
            Files that are .up.sql files under the migrations directory
        """
        migrations_parts = Path(self.migrations_dir).parts
        result = []
        for f in files:
            if f.parts[: len(migrations_parts)] == migrations_parts and f.name.endswith(".up.sql"):
                result.append(f)
        return result
