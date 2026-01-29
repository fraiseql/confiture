"""CLI commands for migration generation from pgGit.

These commands generate Confiture migration files from pgGit branch history.
The generated migrations can be deployed to any environment, including
production databases that do NOT have pgGit installed.

Usage:
    confiture generate from-branch feature/payments
    confiture generate from-branch feature/payments --combined
    confiture generate preview feature/payments
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

# Create Rich console for pretty output
console = Console()

# Create generate subcommand group
generate_app = typer.Typer(
    help="Generate migrations from pgGit branches",
    no_args_is_help=True,
)


def _get_generator(config_path: Path):
    """Create a MigrationGenerator from config file.

    Args:
        config_path: Path to environment config file

    Returns:
        Tuple of (MigrationGenerator, Connection)

    Raises:
        typer.Exit: If pgGit is not available
    """
    from confiture.core.connection import create_connection
    from confiture.integrations.pggit import (
        MigrationGenerator,
        PgGitNotAvailableError,
        is_pggit_available,
    )

    # Load config and create connection
    conn = create_connection(config_path)

    # Check if pgGit is available
    if not is_pggit_available(conn):
        console.print("[red]pgGit extension is not installed on this database.[/red]")
        console.print("\n[yellow]To install pgGit:[/yellow]")
        console.print("  CREATE EXTENSION pggit CASCADE;")
        console.print("\n[dim]Note: pgGit is for development databases only.[/dim]")
        conn.close()
        raise typer.Exit(1)

    try:
        generator = MigrationGenerator(conn)
        return generator, conn
    except PgGitNotAvailableError as e:
        console.print(f"[red]{e}[/red]")
        conn.close()
        raise typer.Exit(1) from e


@generate_app.command("from-branch")
def generate_from_branch(
    branch: str = typer.Argument(..., help="Branch name to generate migrations from"),
    base: str = typer.Option(
        "main",
        "--base",
        "-b",
        help="Base branch to compare against",
    ),
    output: Path = typer.Option(
        Path("db/migrations"),
        "--output",
        "-o",
        help="Output directory for migration files",
    ),
    combined: bool = typer.Option(
        False,
        "--combined",
        "-c",
        help="Generate a single combined migration instead of multiple",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        help="Configuration file",
    ),
) -> None:
    """Generate migrations from a pgGit branch.

    Analyzes commits on BRANCH that aren't in BASE and generates
    Confiture migration files that can be deployed to production.

    Examples:
        confiture generate from-branch feature/payments
        confiture generate from-branch feature/payments --combined
        confiture generate from-branch feature/payments -o db/migrations
        confiture generate from-branch hotfix/bug-123 --base release/1.0
    """
    try:
        generator, conn = _get_generator(config)

        console.print(f"[cyan]Generating migrations from branch '{branch}'...[/cyan]")
        console.print(f"[dim]Base branch: {base}[/dim]\n")

        if combined:
            migration = generator.generate_combined(branch, base, output)
            if migration:
                console.print("[green]Generated combined migration:[/green]")
                console.print(f"  File: {output / f'{migration.version}_{migration.name}.py'}")
                console.print(f"  Changes: {migration.metadata.get('changes_count', 'N/A')}")
            else:
                console.print("[yellow]No changes between branches - nothing to generate.[/yellow]")
        else:
            migrations = generator.generate_from_branch(branch, base, output)
            if migrations:
                console.print(f"[green]Generated {len(migrations)} migration(s):[/green]")
                for m in migrations:
                    console.print(f"  - {m.version}_{m.name}.py")
                console.print(f"\n[dim]Output directory: {output.absolute()}[/dim]")
            else:
                console.print("[yellow]No changes between branches - nothing to generate.[/yellow]")

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error generating migrations: {e}[/red]")
        raise typer.Exit(1) from e


@generate_app.command("preview")
def preview_generation(
    branch: str = typer.Argument(..., help="Branch name to preview"),
    base: str = typer.Option(
        "main",
        "--base",
        "-b",
        help="Base branch to compare against",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        help="Configuration file",
    ),
) -> None:
    """Preview what migrations would be generated.

    Shows changes without writing any files. Use this to review
    what would be generated before running `generate from-branch`.

    Examples:
        confiture generate preview feature/payments
        confiture generate preview feature/payments --base develop
    """
    try:
        generator, conn = _get_generator(config)

        console.print(f"[cyan]Previewing migrations from '{branch}' vs '{base}'...[/cyan]\n")

        changes = generator.preview(branch, base)

        if not changes:
            console.print("[yellow]No changes between branches.[/yellow]")
            conn.close()
            return

        # Create table
        table = Table(title=f"Changes: {base} → {branch}")
        table.add_column("Operation", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Name", style="white")
        table.add_column("Has DDL", style="dim")

        for change in changes:
            op = change["operation"]
            op_color = {
                "CREATE": "green",
                "ALTER": "yellow",
                "DROP": "red",
            }.get(op, "white")

            has_ddl = "Yes" if change["has_new_ddl"] else "No"

            table.add_row(
                f"[{op_color}]{op}[/{op_color}]",
                change["object_type"],
                change["object_name"],
                has_ddl,
            )

        console.print(table)
        console.print(f"\n[dim]Total changes: {len(changes)}[/dim]")
        console.print(
            "\n[dim]Run 'confiture generate from-branch' to generate migration files.[/dim]"
        )

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error previewing: {e}[/red]")
        raise typer.Exit(1) from e


@generate_app.command("diff")
def show_diff(
    branch: str = typer.Argument(..., help="Branch name to diff"),
    base: str = typer.Option(
        "main",
        "--base",
        "-b",
        help="Base branch to compare against",
    ),
    show_sql: bool = typer.Option(
        False,
        "--show-sql",
        "-s",
        help="Show the actual SQL for each change",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        help="Configuration file",
    ),
) -> None:
    """Show detailed diff between branches.

    Similar to preview but can show the actual SQL statements.

    Examples:
        confiture generate diff feature/payments
        confiture generate diff feature/payments --show-sql
    """
    try:
        from confiture.core.connection import create_connection
        from confiture.integrations.pggit import PgGitClient, is_pggit_available

        conn = create_connection(config)

        if not is_pggit_available(conn):
            console.print("[red]pgGit not available.[/red]")
            conn.close()
            raise typer.Exit(1)

        client = PgGitClient(conn)
        diff = client.diff(base, branch)

        if not diff:
            console.print("[yellow]No differences between branches.[/yellow]")
            conn.close()
            return

        console.print(f"[cyan]Diff: {base} → {branch}[/cyan]\n")

        for entry in diff:
            op = entry.operation
            op_color = {"CREATE": "green", "ALTER": "yellow", "DROP": "red"}.get(op, "white")

            console.print(
                f"[{op_color}]{op}[/{op_color}] {entry.object_type} [bold]{entry.object_name}[/bold]"
            )

            if show_sql and entry.new_ddl:
                console.print(
                    f"[dim]  {entry.new_ddl[:200]}{'...' if len(entry.new_ddl) > 200 else ''}[/dim]"
                )

        console.print(f"\n[dim]Total: {len(diff)} change(s)[/dim]")

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
