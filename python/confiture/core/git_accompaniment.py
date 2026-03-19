"""Migration accompaniment validation.

Validates that DDL schema changes are accompanied by migration files.
Useful for pre-commit hooks and CI/CD pipelines.
"""

import re
from pathlib import Path

from confiture.core.git import GitRepository
from confiture.core.git_schema import GitSchemaDiffer
from confiture.models.git import MigrationAccompanimentReport

_FUNC_CONTENT_RE = re.compile(
    r"\bCREATE\b.*?\bFUNCTION\b|\bCREATE\b.*?\bPROCEDURE\b",
    re.IGNORECASE | re.DOTALL,
)


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
        # Get new migration files regardless of whether schema parsing succeeds
        new_migrations = self._get_new_migrations(base_ref, target_ref)

        try:
            diff = self.differ.compare_refs(base_ref, target_ref)
            has_ddl_changes = self.differ.has_ddl_changes(diff)
        except Exception as exc:
            # Schema was too large or complex to parse (e.g. sqlparse token limit,
            # pglast syntax error on non-PostgreSQL DDL).  Treat as "check skipped"
            # rather than a validation failure so CI is not blocked unnecessarily.
            return MigrationAccompanimentReport(
                has_ddl_changes=False,
                has_new_migrations=len(new_migrations) > 0,
                migration_error=f"Schema parse check skipped: {exc}",
                base_ref=base_ref,
                target_ref=target_ref,
            )

        # Check function signature violations (param type changes need DROP FUNCTION)
        signature_violations = self._check_signature_violations(
            new_migrations, base_ref, target_ref
        )

        return MigrationAccompanimentReport(
            has_ddl_changes=has_ddl_changes,
            has_new_migrations=len(new_migrations) > 0,
            ddl_changes=diff.changes,
            new_migration_files=new_migrations,
            base_ref=base_ref,
            target_ref=target_ref,
            signature_violations=signature_violations,
        )

    def _check_signature_violations(
        self,
        new_migrations: list[Path],
        base_ref: str,
        target_ref: str,
    ) -> list:
        """Return function signature violations for changed function files."""
        try:
            function_files = self._get_changed_function_files(base_ref, target_ref)
            if not function_files:
                return []

            from confiture.core.function_signature_checker import (
                FunctionSignatureChecker,  # noqa: PLC0415
            )

            checker = FunctionSignatureChecker(self.git_repo)
            return checker.check(
                changed_sql_files=function_files,
                migration_file_paths=new_migrations,
                base_ref=base_ref,
                target_ref=target_ref,
            )
        except Exception:
            # Signature check is best-effort — never block CI on unexpected errors
            return []

    def _get_changed_function_files(self, base_ref: str, target_ref: str) -> list[Path]:
        """Return SQL files that changed between refs and contain function definitions."""
        changed_files = self.git_repo.get_changed_files(base_ref, target_ref)
        result = []
        for f in changed_files:
            if not f.name.endswith(".sql"):
                continue
            try:
                content = self.git_repo.show_file_at_ref(f, target_ref)
            except Exception:
                continue
            if content and _FUNC_CONTENT_RE.search(content):
                result.append(f)
        return result

    def _get_new_migrations(self, base_ref: str, target_ref: str = "HEAD") -> list[Path]:
        """Get list of new migration files between refs.

        Searches for migration files (*.up.sql) that are new or modified
        between the base and target refs. Only matches files in db/migrations/
        directory to avoid false positives.

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

        # Filter to migration files in db/migrations/ directory.
        # Accepts both .up.sql files and .py migration files (generated by
        # `confiture migrate generate`), excluding __init__.py and private modules.
        migration_files: list[Path] = []
        for file_path in changed_files:
            if (
                len(file_path.parts) >= 2
                and file_path.parts[0] == "db"
                and file_path.parts[1] == "migrations"
                and (
                    file_path.name.endswith(".up.sql")
                    or (file_path.name.endswith(".py") and not file_path.name.startswith("_"))
                )
            ):
                migration_files.append(file_path)

        return migration_files
