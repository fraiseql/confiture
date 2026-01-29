"""Migration accompaniment validation.

Validates that DDL schema changes are accompanied by migration files.
Useful for pre-commit hooks and CI/CD pipelines.
"""

from pathlib import Path

from confiture.core.git import GitRepository
from confiture.core.git_schema import GitSchemaDiffer
from confiture.models.git import MigrationAccompanimentReport


class MigrationAccompanimentChecker:
    """Check if DDL changes are accompanied by migration files.

    When schema changes, there should be corresponding migration files
    that explain how to apply those changes to existing databases.

    Attributes:
        env: Environment name
        repo_path: Repository root directory
        git_repo: GitRepository instance
        differ: GitSchemaDiffer instance

    Example:
        >>> checker = MigrationAccompanimentChecker("local", Path("."))
        >>> report = checker.check_accompaniment("origin/main", "HEAD")
        >>> if not report.is_valid:
        ...     print(f"Error: DDL without migrations: {report.summary()}")
    """

    def __init__(self, env: str, repo_path: Path | None = None):
        """Initialize accompaniment checker.

        Args:
            env: Environment name (e.g., "local", "production")
            repo_path: Repository root directory (default: current directory)
        """
        self.env = env
        self.repo_path = repo_path or Path.cwd()
        self.git_repo = GitRepository(self.repo_path)
        self.differ = GitSchemaDiffer(env, self.repo_path)

    def check_accompaniment(
        self, base_ref: str, target_ref: str = "HEAD"
    ) -> MigrationAccompanimentReport:
        """Check if DDL changes are accompanied by migrations.

        Validates:
        1. Detects DDL changes between refs
        2. Finds new migration files between refs
        3. Reports whether changes are properly accompanied

        Args:
            base_ref: Base git reference (e.g., "origin/main")
            target_ref: Target git reference (default "HEAD")

        Returns:
            MigrationAccompanimentReport with validation results

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git operations fail

        Example:
            >>> checker = MigrationAccompanimentChecker("local")
            >>> report = checker.check_accompaniment("HEAD~1", "HEAD")
            >>> print(f"Has DDL: {report.has_ddl_changes}")
            >>> print(f"Has migrations: {report.has_new_migrations}")
            >>> print(f"Valid: {report.is_valid}")
        """
        # Get schema diff to detect DDL changes
        diff = self.differ.compare_refs(base_ref, target_ref)
        has_ddl_changes = self.differ.has_ddl_changes(diff)

        # Get new migration files
        new_migrations = self._get_new_migrations(base_ref, target_ref)
        has_new_migrations = len(new_migrations) > 0

        return MigrationAccompanimentReport(
            has_ddl_changes=has_ddl_changes,
            has_new_migrations=has_new_migrations,
            ddl_changes=diff.changes,
            new_migration_files=new_migrations,
            base_ref=base_ref,
            target_ref=target_ref,
        )

    def _get_new_migrations(
        self, base_ref: str, target_ref: str = "HEAD"
    ) -> list[Path]:
        """Get list of new migration files between refs.

        Searches for migration files (*.up.sql) that are new or modified
        between the base and target refs.

        Args:
            base_ref: Base git reference
            target_ref: Target git reference

        Returns:
            List of new/modified migration file paths

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git operations fail
        """
        # Get all changed files between refs
        changed_files = self.git_repo.get_changed_files(base_ref, target_ref)

        # Filter to migration files (typically in db/migrations/)
        migration_files: list[Path] = []
        for file_path in changed_files:
            # Check if file is in migrations directory and is an up migration
            if "migrations" in file_path.parts and file_path.name.endswith(".up.sql"):
                migration_files.append(file_path)

        return migration_files
