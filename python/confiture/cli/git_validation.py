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
            elif not report.has_ddl_changes and not report.has_signature_violations:
                console.print("[green]✅ No DDL changes detected[/green]")
            elif report.is_valid:
                console.print("[green]✅ DDL changes accompanied by migrations[/green]")
                console.print(f"   Changes: {len(report.ddl_changes)}")
                console.print(f"   Migrations: {len(report.new_migration_files)}")
            else:
                if report.has_ddl_changes and not report.has_new_migrations:
                    console.print("[red]❌ DDL changes without migration files[/red]")
                    console.print(f"   Changes: {len(report.ddl_changes)}")
                    console.print("   DDL changes found but no migrations added")
                if report.signature_violations:
                    console.print(
                        "[red]❌ Function parameter type changes detected without DROP FUNCTION[/red]"
                    )
                    for v in report.signature_violations:
                        console.print(f"   • {v.function_key}")
                        console.print(f"     Old signature: {v.old_signature}")
                        console.print(f"     New signature: {v.new_signature}")
                        console.print(
                            f"     [yellow]Fix: add DROP FUNCTION {v.old_signature}; "
                            f"before CREATE OR REPLACE in a migration[/yellow]"
                        )

        return report.to_dict()

    except (NotAGitRepositoryError, GitError) as e:
        if format_output == "text":
            console.print(f"[red]❌ Git validation error: {e}[/red]")
        raise


def _render_grant_report(report, console: Console) -> None:
    """Render the semantic grant-accompaniment report for human eyes (issue #162).

    Three sections, driven by the report: unmatched grants (the hard failure,
    naming each grant + where it changed + the migrations inspected),
    degradation notes (shown, non-fatal when a migration is present), and the
    pass line. Defensive against partially-stubbed report objects.
    """
    unmatched = getattr(report, "unmatched_grants", None)
    unmatched = unmatched if isinstance(unmatched, list) else []
    notes = getattr(report, "unverifiable_notes", None)
    notes = notes if isinstance(notes, list) else []

    if not report.has_grant_changes:
        console.print("[green]✅ No grant file changes detected[/green]")
        return

    if unmatched:
        console.print("[red]❌ Grant changes not carried by any migration:[/red]\n")
        for grant in unmatched:
            statement = grant.get("statement", "<grant>") if isinstance(grant, dict) else str(grant)
            changed_in = grant.get("changed_in") if isinstance(grant, dict) else None
            inspected = grant.get("migrations_inspected") if isinstance(grant, dict) else None
            console.print(f"   [bold]{statement}[/bold]")
            if changed_in:
                console.print(f"     changed in {changed_in}")
            if inspected:
                console.print(f"     not found in: {', '.join(inspected)}")
            else:
                console.print("     no accompanying migration carries it")
            console.print("")
        console.print(
            "  Migrate environments (staging, production) apply grants ONLY via migrations;\n"
            "  these grants will not reach them. Add each to a migration (SQL or Python),\n"
            "  or run with --allow-grant-only if this branch uses build-only deployment."
        )
        if notes:
            console.print("")

    if notes:
        if report.is_valid:
            console.print(
                "[yellow]⚠️  Could not statically verify (relying on migration presence):[/yellow]"
            )
        else:
            console.print("[yellow]⚠️  Could not statically verify:[/yellow]")
        for note in notes:
            console.print(f"     - {note}")
        if not report.is_valid and not unmatched:
            console.print(
                "\n  No accompanying migration was found, so these unverifiable grant\n"
                "  changes are not guaranteed to reach migrate environments. Add a\n"
                "  migration, or run with --allow-grant-only for build-only branches."
            )

    if report.is_valid and not notes:
        console.print("[green]✅ Grant changes accompanied by migrations[/green]")
        console.print(f"   Grant files: {len(report.grant_files_changed)}")
        console.print(f"   Migrations: {len(report.migration_files_staged)}")
    elif report.is_valid:
        console.print("\n[green]✅ Grant changes carried by accompanying migrations[/green]")


def validate_grant_accompaniment(
    base_ref: str,
    target_ref: str,
    staged_only: bool,
    console: Console,
    format_output: str = "text",
    grant_dir: str = "db/7_grant",
    migrations_dir: str = "db/migrations",
) -> dict:
    """Validate that grant file changes are carried by accompanying migrations.

    Semantic (issue #162): verifies that each *changed* GRANT/REVOKE statement
    in ``grant_dir`` is present in an accompanying migration (``.up.sql`` or
    ``.py``). Grants that can't be statically represented degrade to a
    file-presence check and are surfaced as notes — never silently passed.

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
            _render_grant_report(report, console)

        return report.to_dict()

    except (NotAGitRepositoryError, GitError) as e:
        if format_output == "text":
            console.print(f"[red]❌ Git validation error: {e}[/red]")
        raise
