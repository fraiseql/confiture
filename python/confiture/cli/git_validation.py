"""CLI helpers for git-aware schema validation.

Provides helpers for integrating git validation into CLI commands.
"""

from rich.console import Console

from confiture.core.git import GitRepository
from confiture.core.git_accompaniment import MigrationAccompanimentChecker
from confiture.core.git_schema import GitSchemaDiffer
from confiture.core.grant_accompaniment import GrantAccompanimentChecker
from confiture.exceptions import GitError, NotAGitRepositoryError


def validate_git_flags_in_repo() -> GitRepository:
    """Validate that we're in a git repository.

    Raises:
        NotAGitRepositoryError: If not in a git repository

    Returns:
        GitRepository instance for the current directory
    """
    repo = GitRepository()
    if not repo.is_git_repo():
        raise NotAGitRepositoryError(
            "Git validation requires a git repository. Current directory is not a git repository."
        )
    return repo


def validate_git_drift(
    env: str,
    base_ref: str,
    target_ref: str,
    console: Console,
    format_output: str = "text",
) -> dict:
    """Validate schema drift between git refs.

    Args:
        env: Environment name
        base_ref: Base git reference
        target_ref: Target git reference
        console: Rich console for output
        format_output: Output format (text or json)

    Returns:
        Dictionary with validation results

    Raises:
        NotAGitRepositoryError: If not in a git repository
        GitError: If git operations fail
    """
    try:
        validate_git_flags_in_repo()

        differ = GitSchemaDiffer(env)
        diff = differ.compare_refs(base_ref, target_ref)

        if format_output == "text":
            if diff.has_changes():
                console.print("[yellow]⚠️  Schema differences detected[/yellow]")
                for change in diff.changes:
                    console.print(f"  • {change}")
            else:
                console.print("[green]✅ No schema differences detected[/green]")

        return {
            "passed": not diff.has_changes(),
            "changes": [
                {
                    "type": c.type,
                    "table": c.table,
                    "column": c.column,
                    "details": c.details,
                }
                for c in diff.changes
            ],
            "base_ref": base_ref,
            "target_ref": target_ref,
        }

    except (NotAGitRepositoryError, GitError) as e:
        if format_output == "text":
            console.print(f"[red]❌ Git validation error: {e}[/red]")
        raise


def validate_migration_accompaniment(
    env: str,
    base_ref: str,
    target_ref: str,
    console: Console,
    format_output: str = "text",
) -> dict:
    """Validate that DDL changes have migration files.

    Args:
        env: Environment name
        base_ref: Base git reference
        target_ref: Target git reference
        console: Rich console for output
        format_output: Output format (text or json)

    Returns:
        Dictionary with validation results

    Raises:
        NotAGitRepositoryError: If not in a git repository
        GitError: If git operations fail
    """
    try:
        validate_git_flags_in_repo()

        checker = MigrationAccompanimentChecker(env)
        report = checker.check_accompaniment(base_ref, target_ref)

        if format_output == "text":
            if report.migration_error:
                console.print(
                    f"[yellow]⚠️  Schema parse check skipped: {report.migration_error}[/yellow]"
                )
                console.print(
                    "[yellow]   Schema may be too large for static analysis "
                    "— DDL accompaniment check was not run.[/yellow]"
                )
            elif not report.has_ddl_changes:
                console.print("[green]✅ No DDL changes detected[/green]")
            elif report.is_valid:
                console.print("[green]✅ DDL changes accompanied by migrations[/green]")
                console.print(f"   Changes: {len(report.ddl_changes)}")
                console.print(f"   Migrations: {len(report.new_migration_files)}")
            else:
                console.print("[red]❌ DDL changes without migration files[/red]")
                console.print(f"   Changes: {len(report.ddl_changes)}")
                console.print("   DDL changes found but no migrations added")

        return report.to_dict()

    except (NotAGitRepositoryError, GitError) as e:
        if format_output == "text":
            console.print(f"[red]❌ Git validation error: {e}[/red]")
        raise


def validate_grant_accompaniment(
    base_ref: str,
    target_ref: str,
    staged_only: bool,
    console: Console,
    format_output: str = "text",
    grant_dir: str = "db/7_grant",
    migrations_dir: str = "db/migrations",
) -> dict:
    """Validate that grant file changes have migration files.

    Uses file-level detection: if any file under grant_dir changed, at least
    one .up.sql migration must also be present in the changeset.

    Args:
        base_ref: Base git reference (used when staged_only=False)
        target_ref: Target git reference (used when staged_only=False)
        staged_only: If True, check staged files only (pre-commit mode)
        console: Rich console for output
        format_output: Output format (text or json)
        grant_dir: Relative path to grant directory (default: "db/7_grant")
        migrations_dir: Relative path to migrations directory (default: "db/migrations")

    Returns:
        Dictionary with validation results

    Raises:
        NotAGitRepositoryError: If not in a git repository
        GitError: If git operations fail
    """
    try:
        validate_git_flags_in_repo()

        checker = GrantAccompanimentChecker(
            grant_dir=grant_dir,
            migrations_dir=migrations_dir,
        )
        report = checker.check_accompaniment(
            base_ref=base_ref,
            target_ref=target_ref,
            staged_only=staged_only,
        )

        if format_output == "text":
            if not report.has_grant_changes:
                console.print("[green]✅ No grant file changes detected[/green]")
            elif report.is_valid:
                console.print("[green]✅ Grant changes accompanied by migrations[/green]")
                console.print(f"   Grant files: {len(report.grant_files_changed)}")
                console.print(f"   Migrations: {len(report.migration_files_staged)}")
            else:
                console.print(
                    "[red]❌ Grant changes without migration files[/red]\n\n  Grant files changed:"
                )
                for f in report.grant_files_changed:
                    console.print(f"    {f}")
                console.print(
                    "\n"
                    "  No migration file (.up.sql) was staged.\n"
                    "\n"
                    "  Migrate environments (staging, production) will NOT apply these grants\n"
                    "  until they appear in a migration file.\n"
                    "\n"
                    "  Fix: Add GRANT statements to a new migration, or run with --allow-grant-only\n"
                    "  if this branch uses build-only deployment."
                )

        return report.to_dict()

    except (NotAGitRepositoryError, GitError) as e:
        if format_output == "text":
            console.print(f"[red]❌ Git validation error: {e}[/red]")
        raise
