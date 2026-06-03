"""CLI commands for pgGit branch operations.

These commands provide Git-like schema branching for development databases.
pgGit must be installed on the target database for these commands to work.

NOTE: pgGit is for DEVELOPMENT and STAGING databases only.
Do NOT install pgGit on production databases.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from confiture.cli.error_json import fail
from confiture.cli.helpers import is_json
from confiture.exceptions import ConfiturError

# Create Rich console for pretty output
console = Console()

# Create branch subcommand group
branch_app = typer.Typer(
    help="Schema branching commands (requires pgGit)",
    no_args_is_help=True,
)


def _get_pggit_client(config_path: Path):
    """Create a pgGit client from config file.

    Args:
        config_path: Path to environment config file

    Returns:
        Tuple of (PgGitClient, Connection)

    Raises:
        ConfiturError: If pgGit is not available (PRECON_1000); the calling
            command routes it through the fail() boundary.
    """
    from confiture.core.connection import create_connection
    from confiture.integrations.pggit import (
        PgGitClient,
        PgGitNotAvailableError,
        is_pggit_available,
    )

    # Load config and create connection
    conn = create_connection(config_path)

    # Check if pgGit is available
    if not is_pggit_available(conn):
        conn.close()
        raise ConfiturError(
            "pgGit extension is not installed on this database.",
            error_code="PRECON_1000",
            resolution_hint=(
                "Install it with `CREATE EXTENSION pggit CASCADE;` "
                "(pgGit is for development databases only)."
            ),
        )

    try:
        client = PgGitClient(conn)
        return client, conn
    except PgGitNotAvailableError as e:
        conn.close()
        raise ConfiturError(str(e), error_code="PRECON_1000") from e


@branch_app.command("list")
def branch_list(
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    format_output: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table or json (default: table)",
    ),
) -> None:
    """List all schema branches.

    Shows all branches with current branch highlighted.

    Examples:
        confiture branch list
        confiture branch list --format json
    """
    import json

    try:
        client, conn = _get_pggit_client(config)

        branches = client.list_branches()
        current = client.get_branch()

        if format_output == "json":
            output = {
                "current": current.name if current else None,
                "branches": [
                    {
                        "name": b.name,
                        "created_at": b.created_at.isoformat() if b.created_at else None,
                        "commit_count": b.commit_count,
                        "is_current": b.name == (current.name if current else None),
                    }
                    for b in branches
                ],
            }
            console.print(json.dumps(output, indent=2))
        else:
            # Table format
            table = Table(title="Schema Branches")
            table.add_column("", style="green", width=2)
            table.add_column("Branch", style="cyan")
            table.add_column("Created", style="dim")
            table.add_column("Commits", style="yellow", justify="right")

            for branch in branches:
                is_current = branch.name == (current.name if current else None)
                marker = "*" if is_current else ""
                created = branch.created_at.strftime("%Y-%m-%d") if branch.created_at else "-"

                table.add_row(
                    marker,
                    branch.name,
                    created,
                    str(branch.commit_count or 0),
                )

            console.print(table)

            if current:
                console.print(f"\n[dim]Current branch: {current.name}[/dim]")

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        fail(e, json_mode=is_json(format_output))


@branch_app.command("create")
def branch_create(
    name: str = typer.Argument(..., help="Name of the new branch"),
    from_branch: str = typer.Option(
        None,
        "--from",
        "-f",
        help="Parent branch (default: current branch)",
    ),
    checkout: bool = typer.Option(
        True,
        "--checkout/--no-checkout",
        help="Checkout new branch after creation (default: on)",
    ),
    copy_data: bool = typer.Option(
        True,
        "--copy-data/--no-copy-data",
        help="Copy data from parent branch (default: on)",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
) -> None:
    """Create a new schema branch.

    Creates a new branch from the current branch or specified parent.
    By default, checks out the new branch after creation.

    Examples:
        confiture branch create feature/payments
        confiture branch create hotfix/bug-123 --from main
        confiture branch create experiment --no-checkout
    """
    try:
        client, conn = _get_pggit_client(config)

        # Create branch
        console.print(f"[cyan]Creating branch '{name}'...[/cyan]")
        branch = client.create_branch(
            name=name,
            parent_branch=from_branch,
            copy_data=copy_data,
        )

        console.print(f"[green]Branch '{branch.name}' created.[/green]")

        # Checkout if requested
        if checkout:
            client.checkout(name)
            console.print(f"[green]Switched to branch '{name}'[/green]")

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        fail(e, json_mode=False)


@branch_app.command("checkout")
def branch_checkout(
    name: str = typer.Argument(..., help="Branch name to checkout"),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
) -> None:
    """Switch to a different schema branch.

    Changes the active schema branch. All subsequent schema changes
    will be tracked on this branch.

    Examples:
        confiture branch checkout main
        confiture branch checkout feature/payments
    """
    try:
        client, conn = _get_pggit_client(config)

        console.print(f"[cyan]Switching to branch '{name}'...[/cyan]")
        client.checkout(name)
        console.print(f"[green]Switched to branch '{name}'[/green]")

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        fail(e, json_mode=False)


@branch_app.command("delete")
def branch_delete(
    name: str = typer.Argument(..., help="Branch name to delete"),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force delete even if branch has unmerged commits",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
) -> None:
    """Delete a schema branch.

    Removes the specified branch. Cannot delete the current branch
    or protected branches (main, master) without --force.

    Examples:
        confiture branch delete feature/old-experiment
        confiture branch delete stale-branch --force
    """
    try:
        client, conn = _get_pggit_client(config)

        # Check if trying to delete current branch
        current = client.get_branch()
        if current and current.name == name:
            conn.close()
            raise ConfiturError(
                "Cannot delete the current branch.",
                resolution_hint=(
                    "Checkout a different branch first: confiture branch checkout main"
                ),
            )

        # Confirm deletion
        if not force and not typer.confirm(f"Delete branch '{name}'?"):
            console.print("[yellow]Aborted.[/yellow]")
            conn.close()
            return

        console.print(f"[cyan]Deleting branch '{name}'...[/cyan]")
        client.delete_branch(name, force=force)
        console.print(f"[green]Branch '{name}' deleted.[/green]")

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        fail(e, json_mode=False)


@branch_app.command("status")
def branch_status(
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
) -> None:
    """Show current branch status and uncommitted changes.

    Displays the current branch and any schema changes that haven't
    been committed yet.

    Examples:
        confiture branch status
    """
    try:
        client, conn = _get_pggit_client(config)

        status = client.status()

        # Display current branch
        console.print(f"[cyan]On branch:[/cyan] {status.current_branch or '(detached)'}")

        # Display changes
        if status.has_changes:
            console.print(f"\n[yellow]Uncommitted changes ({status.change_count}):[/yellow]")

            for change in status.changes:
                if change.change_type == "added":
                    console.print(f"  [green]+ {change.object_type}: {change.object_name}[/green]")
                elif change.change_type == "modified":
                    console.print(
                        f"  [yellow]~ {change.object_type}: {change.object_name}[/yellow]"
                    )
                elif change.change_type == "deleted":
                    console.print(f"  [red]- {change.object_type}: {change.object_name}[/red]")
                else:
                    console.print(f"  [dim]? {change.object_type}: {change.object_name}[/dim]")

            console.print("\n[dim]Use 'confiture branch commit' to commit changes.[/dim]")
        else:
            console.print("\n[green]Working tree clean - no uncommitted changes.[/green]")

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        fail(e, json_mode=False)


@branch_app.command("commit")
def branch_commit(
    message: str = typer.Argument(..., help="Commit message"),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
) -> None:
    """Commit current schema changes.

    Records the current schema state as a commit on the current branch.
    Similar to 'git commit' but for database schema.

    Examples:
        confiture branch commit "Add users table"
        confiture branch commit "feat: add payment processing tables"
    """
    try:
        client, conn = _get_pggit_client(config)

        # Check for changes
        status = client.status()
        if not status.has_changes:
            console.print("[yellow]No changes to commit.[/yellow]")
            conn.close()
            return

        console.print(f"[cyan]Committing {status.change_count} change(s)...[/cyan]")
        commit = client.commit(message)

        console.print(f"[green]Created commit {commit.hash[:8]}[/green]")
        console.print(f"[dim]{message}[/dim]")

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        fail(e, json_mode=False)


@branch_app.command("log")
def branch_log(
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        help="Maximum number of commits to show",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
) -> None:
    """Show commit history for current branch.

    Displays recent commits on the current branch.

    Examples:
        confiture branch log
        confiture branch log --limit 20
    """
    try:
        client, conn = _get_pggit_client(config)

        commits = client.log(limit=limit)

        if not commits:
            console.print("[yellow]No commits on this branch.[/yellow]")
            conn.close()
            return

        console.print(f"[cyan]Commit history (showing {len(commits)} of {limit} max):[/cyan]\n")

        for commit in commits:
            console.print(f"[yellow]commit {commit.hash}[/yellow]")
            if commit.author:
                console.print(f"Author: {commit.author}")
            if commit.timestamp:
                console.print(f"Date:   {commit.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            console.print(f"\n    {commit.message}\n")

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        fail(e, json_mode=False)


@branch_app.command("merge")
def branch_merge(
    source: str = typer.Argument(..., help="Source branch to merge from"),
    target: str = typer.Option(
        None,
        "--into",
        help="Target branch (default: current branch)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be merged without making changes",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
) -> None:
    """Merge one branch into another.

    Merges schema changes from source branch into target branch.
    If conflicts are detected, provides guidance for resolution.

    Examples:
        confiture branch merge feature/payments
        confiture branch merge feature/users --into main
        confiture branch merge feature/experiment --dry-run
    """
    try:
        client, conn = _get_pggit_client(config)

        target_branch = target or (client.get_branch().name if client.get_branch() else "main")

        if dry_run:
            console.print(f"[cyan]Dry run: merge '{source}' into '{target_branch}'[/cyan]")
            # For dry-run, just show diff
            diff = client.diff(source, target_branch)
            if diff:
                console.print(f"\n[yellow]Changes to be merged ({len(diff)}):[/yellow]")
                for entry in diff:
                    console.print(f"  {entry.change_type}: {entry.object_type} {entry.object_name}")
            else:
                console.print("[green]No changes to merge - branches are identical.[/green]")
            conn.close()
            return

        console.print(f"[cyan]Merging '{source}' into '{target_branch}'...[/cyan]")
        result = client.merge(source, target_branch)

        if result.success:
            console.print(f"[green]Successfully merged '{source}' into '{target_branch}'[/green]")
            if result.commit_hash:
                console.print(f"[dim]Merge commit: {result.commit_hash[:8]}[/dim]")
        else:
            console.print(f"[red]Merge failed: {result.message}[/red]")

            if result.conflicts:
                console.print(f"\n[yellow]Conflicts detected ({len(result.conflicts)}):[/yellow]")
                for conflict in result.conflicts:
                    console.print(
                        f"  - {conflict.get('object_type', 'UNKNOWN')}: {conflict.get('object_name', 'unknown')}"
                    )

                console.print(
                    "\n[dim]Resolve conflicts manually or abort with 'confiture branch merge-abort'[/dim]"
                )

            conn.close()
            raise ConfiturError(
                f"Merge failed: {result.message}",
                error_code="PGGIT_900",
            )

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        fail(e, json_mode=False)


@branch_app.command("merge-abort")
def branch_merge_abort(
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
) -> None:
    """Abort an in-progress merge.

    Cancels a merge that has conflicts and restores the previous state.

    Examples:
        confiture branch merge-abort
    """
    try:
        client, conn = _get_pggit_client(config)

        console.print("[cyan]Aborting merge...[/cyan]")
        client.abort_merge()
        console.print("[green]Merge aborted. Working tree restored.[/green]")

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        fail(e, json_mode=False)


@branch_app.command("diff")
def branch_diff(
    source: str = typer.Argument(None, help="Source branch (default: current branch)"),
    target: str = typer.Argument(None, help="Target branch to compare against"),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
) -> None:
    """Show differences between branches.

    Compares schema objects between two branches.

    Examples:
        confiture branch diff                     # Current vs main
        confiture branch diff feature/payments    # feature/payments vs main
        confiture branch diff feature/a feature/b # feature/a vs feature/b
    """
    try:
        client, conn = _get_pggit_client(config)

        # Resolve branch names
        current = client.get_branch()
        source_branch = source or (current.name if current else "main")
        target_branch = target or "main"

        console.print(f"[cyan]Comparing '{source_branch}' to '{target_branch}'...[/cyan]\n")

        diff = client.diff(source_branch, target_branch)

        if not diff:
            console.print("[green]No differences - branches are identical.[/green]")
            conn.close()
            return

        # Group by change type
        added = [d for d in diff if d.change_type == "added"]
        modified = [d for d in diff if d.change_type == "modified"]
        deleted = [d for d in diff if d.change_type == "deleted"]

        if added:
            console.print(f"[green]Added ({len(added)}):[/green]")
            for entry in added:
                console.print(f"  + {entry.object_type}: {entry.object_name}")

        if modified:
            console.print(f"\n[yellow]Modified ({len(modified)}):[/yellow]")
            for entry in modified:
                console.print(f"  ~ {entry.object_type}: {entry.object_name}")

        if deleted:
            console.print(f"\n[red]Deleted ({len(deleted)}):[/red]")
            for entry in deleted:
                console.print(f"  - {entry.object_type}: {entry.object_name}")

        console.print(f"\n[dim]Total: {len(diff)} difference(s)[/dim]")

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        fail(e, json_mode=False)
