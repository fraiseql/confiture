"""Formatter for migrate command output.

Handles text, JSON, and CSV formatting for migration results.
"""

from pathlib import Path

from rich.console import Console

from confiture.cli.formatters.common import handle_output
from confiture.models.results import (
    MigrateDiffResult,
    MigrateDownResult,
    MigrateUpResult,
    MigrateValidateResult,
)


def format_migrate_up_result(
    result: MigrateUpResult,
    format_type: str,
    output_path: Path | None,
    console: Console,
) -> None:
    """Format migrate up result in requested format.

    Args:
        result: MigrateUpResult to format
        format_type: Output format ('text', 'json', or 'csv')
        output_path: Optional file path to write output
        console: Rich console for output
    """
    if format_type == "text":
        # Text output to console
        format_text(result, console)
    else:
        # JSON/CSV output
        csv_data = (
            ["version", "name", "duration_ms", "rows_affected"],
            [
                [m.version, m.name, str(m.execution_time_ms), str(m.rows_affected)]
                for m in result.migrations_applied
            ],
        )
        handle_output(format_type, result.to_dict(), csv_data, output_path, console)


def format_text(result: MigrateUpResult, console: Console) -> None:
    """Format migrate up result as rich text for console output.

    Args:
        result: MigrateUpResult to format
        console: Rich console for output
    """
    if result.success:
        if result.dry_run:
            console.print("[cyan]🔍 Dry-run analysis:[/cyan]")
        else:
            console.print("[green]✅ Successfully applied migrations![/green]")

        if result.migrations_applied:
            console.print(f"\nMigrations: {len(result.migrations_applied)}")
            for migration in result.migrations_applied:
                console.print(
                    f"  • {migration.version}_{migration.name} ({migration.execution_time_ms}ms)"
                )
        else:
            console.print("\n[yellow]No migrations applied[/yellow]")

        if result.total_execution_time_ms > 0:
            console.print(f"\n⏱️ Total time: {result.total_execution_time_ms}ms")

        if result.checksums_verified:
            console.print("[cyan]🔐 Checksums verified[/cyan]")

        if result.warnings:
            console.print("\n[yellow]Warnings:[/yellow]")
            for warning in result.warnings:
                console.print(f"  ⚠️ {warning}")
    else:
        console.print(f"[red]❌ Migration failed: {result.error}[/red]")
        if result.migrations_applied:
            count = len(result.migrations_applied)
            console.print(f"\n[yellow]⚠️ {count} migration(s) were applied before failure[/yellow]")


def format_migrate_down_result(
    result: MigrateDownResult,
    format_type: str,
    output_path: Path | None,
    console: Console,
) -> None:
    """Format migrate down result in requested format.

    Args:
        result: MigrateDownResult to format
        format_type: Output format ('text', 'json', or 'csv')
        output_path: Optional file path to write output
        console: Rich console for output
    """
    if format_type == "text":
        # Text output to console
        format_down_text(result, console)
    else:
        # JSON/CSV output
        csv_data = (
            ["version", "name", "execution_time_ms", "rows_affected"],
            [
                [m.version, m.name, str(m.execution_time_ms), str(m.rows_affected)]
                for m in result.migrations_rolled_back
            ],
        )
        handle_output(format_type, result.to_dict(), csv_data, output_path, console)


def format_down_text(result: MigrateDownResult, console: Console) -> None:
    """Format migrate down result as rich text for console output.

    Args:
        result: MigrateDownResult to format
        console: Rich console for output
    """
    if result.success:
        console.print("[green]✅ Successfully rolled back migrations![/green]")

        if result.migrations_rolled_back:
            console.print(f"\nMigrations: {len(result.migrations_rolled_back)}")
            for migration in result.migrations_rolled_back:
                console.print(
                    f"  • {migration.version}_{migration.name} ({migration.execution_time_ms}ms)"
                )
        else:
            console.print("\n[yellow]No migrations rolled back[/yellow]")

        if result.total_execution_time_ms > 0:
            console.print(f"\n⏱️ Total time: {result.total_execution_time_ms}ms")

        if result.checksums_verified:
            console.print("[cyan]🔐 Checksums verified[/cyan]")

        if result.warnings:
            console.print("\n[yellow]Warnings:[/yellow]")
            for warning in result.warnings:
                console.print(f"  ⚠️ {warning}")
    else:
        console.print(f"[red]❌ Rollback failed: {result.error}[/red]")
        if result.migrations_rolled_back:
            count = len(result.migrations_rolled_back)
            console.print(
                f"\n[yellow]⚠️ {count} migration(s) were rolled back before failure[/yellow]"
            )


def format_migrate_diff_result(
    result: MigrateDiffResult,
    format_type: str,
    output_path: Path | None,
    console: Console,
) -> None:
    """Format migrate diff result in requested format.

    Args:
        result: MigrateDiffResult to format
        format_type: Output format ('text', 'json', or 'csv')
        output_path: Optional file path to write output
        console: Rich console for output
    """
    if format_type == "text":
        format_diff_text(result, console)
    else:
        # JSON/CSV output
        csv_data = (
            ["type", "details"],
            [[c.change_type, c.details] for c in result.changes],
        )
        handle_output(format_type, result.to_dict(), csv_data, output_path, console)


def format_diff_text(result: MigrateDiffResult, console: Console) -> None:
    """Format migrate diff result as rich text for console output.

    Args:
        result: MigrateDiffResult to format
        console: Rich console for output
    """
    if not result.success:
        console.print(f"[red]❌ Diff failed: {result.error}[/red]")
        return

    if not result.has_changes:
        console.print("[green]✅ No changes detected. Schemas are identical.[/green]")
        return

    console.print("[cyan]📊 Schema differences detected:[/cyan]\n")

    for change in result.changes:
        console.print(f"  [{change.change_type}] {change.details}")

    console.print(f"\n📈 Total changes: {len(result.changes)}")

    if result.migration_generated:
        console.print(f"\n[green]✅ Migration generated: {result.migration_file}[/green]")


def format_migrate_validate_result(
    result: MigrateValidateResult,
    format_type: str,
    output_path: Path | None,
    console: Console,
) -> None:
    """Format migrate validate result in requested format.

    Args:
        result: MigrateValidateResult to format
        format_type: Output format ('text', 'json', or 'csv')
        output_path: Optional file path to write output
        console: Rich console for output
    """
    if format_type == "text":
        format_validate_text(result, console)
    else:
        # JSON/CSV output
        csv_data = (
            ["check", "count"],
            [
                ["orphaned_files", str(len(result.orphaned_files))],
                ["duplicate_versions", str(len(result.duplicate_versions))],
                ["fixed_files", str(len(result.fixed_files))],
            ],
        )
        handle_output(format_type, result.to_dict(), csv_data, output_path, console)


def format_validate_text(result: MigrateValidateResult, console: Console) -> None:
    """Format migrate validate result as rich text for console output.

    Args:
        result: MigrateValidateResult to format
        console: Rich console for output
    """
    if not result.success:
        console.print(f"[red]❌ Validation failed: {result.error}[/red]")
        return

    if result.orphaned_files:
        console.print("[yellow]⚠️ Orphaned files found:[/yellow]")
        for f in result.orphaned_files:
            console.print(f"  • {f}")

    if result.duplicate_versions:
        console.print("[red]❌ Duplicate migration versions detected:[/red]")
        for version, files in sorted(result.duplicate_versions.items()):
            console.print(f"  Version {version}:")
            for f in files:
                console.print(f"    • {f}")

    if result.fixed_files:
        console.print("[green]✅ Files fixed:[/green]")
        for f in result.fixed_files:
            console.print(f"  • {f}")

    if result.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for warning in result.warnings:
            console.print(f"  ⚠️ {warning}")

    if result.success and not result.orphaned_files and not result.duplicate_versions:
        console.print("[green]✅ All validation checks passed[/green]")


def show_migration_error_details(
    failed_migration: object,
    exception: BaseException,
    applied_count: int,
    console: Console,
) -> None:
    """Show detailed error information for a failed migration with actionable guidance.

    Args:
        failed_migration: The Migration instance that failed
        exception: The exception that was raised
        applied_count: Number of migrations that succeeded before this one
        console: Rich Console to print to
    """
    from confiture.exceptions import MigrationError

    console.print("\n[red]Failed Migration Details:[/red]")
    console.print(f"  Version: {failed_migration.version}")  # type: ignore[union-attr]
    console.print(f"  Name: {failed_migration.name}")  # type: ignore[union-attr]
    console.print(
        f"  File: db/migrations/{failed_migration.version}_{failed_migration.name}.py"  # type: ignore[union-attr]
    )

    error_message = str(exception)

    if "SQL execution failed" in error_message:
        console.print("  Error Type: SQL Execution Error")
        parts = error_message.split(" | ")
        sql_part = next((part for part in parts if part.startswith("SQL: ")), None)
        error_part = next((part for part in parts if part.startswith("Error: ")), None)

        if sql_part:
            sql_content = sql_part[5:].strip()
            console.print(
                f"  SQL Statement: {sql_content[:100]}{'...' if len(sql_content) > 100 else ''}"
            )

        if error_part:
            db_error = error_part[7:].strip()
            console.print(f"  Database Error: {db_error.split(chr(10))[0]}")

            error_msg = db_error.lower()
            if "syntax error" in error_msg:
                console.print("\n[yellow]🔍 SQL Syntax Error Detected:[/yellow]")
                console.print("  • Check for typos in SQL keywords, table names, or column names")
                console.print(
                    "  • Verify quotes, parentheses, and semicolons are properly balanced"
                )
                if sql_part:
                    sql_content = sql_part[5:].strip()
                    console.print(f'  • Test the SQL manually: psql -c "{sql_content}"')
            elif "does not exist" in error_msg:
                if "schema" in error_msg:
                    console.print("\n[yellow]🔍 Missing Schema Error:[/yellow]")
                    console.print(
                        "  • Create the schema first: CREATE SCHEMA IF NOT EXISTS schema_name;"
                    )
                    console.print("  • Or use the public schema by default")
                elif "table" in error_msg or "relation" in error_msg:
                    console.print("\n[yellow]🔍 Missing Table Error:[/yellow]")
                    console.print("  • Ensure dependent migrations ran first")
                    console.print("  • Check table name spelling and schema qualification")
                elif "function" in error_msg:
                    console.print("\n[yellow]🔍 Missing Function Error:[/yellow]")
                    console.print("  • Define the function before using it")
                    console.print("  • Check function name and parameter types")
            elif "already exists" in error_msg:
                console.print("\n[yellow]🔍 Object Already Exists:[/yellow]")
                console.print("  • Use IF NOT EXISTS clauses for safe creation")
                console.print("  • Check if migration was partially applied")
            elif "permission denied" in error_msg:
                console.print("\n[yellow]🔍 Permission Error:[/yellow]")
                console.print("  • Verify database user has required privileges")
                console.print("  • Check GRANT statements in earlier migrations")

    elif isinstance(exception, MigrationError):
        console.print("  Error Type: Migration Framework Error")
        console.print(f"  Message: {exception}")

        error_msg = str(exception).lower()
        if "already been applied" in error_msg:
            console.print("\n[yellow]🔍 Migration Already Applied:[/yellow]")
            console.print("  • Check migration status: confiture migrate status")
            console.print("  • This migration may have run successfully before")
        elif "connection" in error_msg:
            console.print("\n[yellow]🔍 Database Connection Error:[/yellow]")
            console.print("  • Verify database is running and accessible")
            console.print("  • Check connection string in config file")
            console.print("  • Test connection: psql 'your-connection-string'")

    else:
        console.print(f"  Error Type: {type(exception).__name__}")
        console.print(f"  Message: {exception}")

    console.print("\n[yellow]🛠️  General Troubleshooting:[/yellow]")
    console.print(
        f"  • View migration file: cat db/migrations/{failed_migration.version}_{failed_migration.name}.py"  # type: ignore[union-attr]
    )
    console.print("  • Check database logs for more details")
    console.print("  • Test SQL manually in psql")

    if applied_count > 0:
        console.print(f"  • {applied_count} migration(s) succeeded - database is partially updated")
        console.print("  • Fix the error and re-run: confiture migrate up")
        console.print(f"  • Or rollback and retry: confiture migrate down --steps {applied_count}")
    else:
        console.print("  • No migrations applied yet - database state is clean")
        console.print("  • Fix the error and re-run: confiture migrate up")
