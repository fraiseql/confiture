"""Multi-agent coordination CLI commands for pgGit.

This module provides commands for managing agent intentions and detecting conflicts
in multi-agent development scenarios.

Commands:
- coordinate register    Register a new agent intention
- coordinate list       List all intentions with optional filtering
- coordinate check      Check for conflicts with existing intents
- coordinate status     Show status of a specific intention
- coordinate conflicts  List all conflicts
- coordinate resolve    Mark a conflict as resolved
- coordinate abandon    Abandon an intention
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import typer
from rich.console import Console
from rich.table import Table

from confiture.integrations.pggit.coordination import (
    ConflictSeverity,
    IntentRegistry,
    IntentStatus,
)

# Create sub-app for coordinate commands
coordinate_app = typer.Typer(
    name="coordinate",
    help="Multi-agent coordination for schema changes",
)

console = Console()


def _output_json(data: dict | list, pretty: bool = True) -> None:
    """Output data as JSON.

    Args:
        data: Dictionary or list to output as JSON
        pretty: Whether to pretty-print (indent) the JSON
    """
    import json

    indent = 2 if pretty else None
    print(json.dumps(data, indent=indent))


def _get_connection(database_url: str | None = None) -> psycopg.Connection:
    """Get database connection.

    Args:
        database_url: Optional database URL, uses environment if not provided

    Returns:
        psycopg Connection
    """
    if database_url:
        return psycopg.connect(database_url)

    # Try environment variable
    import os

    url = os.getenv("DATABASE_URL") or os.getenv("CONFITURE_DB_URL")
    if not url:
        console.print(
            "[red]Error:[/red] No database URL provided. Use --db-url or set DATABASE_URL environment variable"
        )
        raise typer.Exit(1)

    return psycopg.connect(url)


@coordinate_app.command()
def register(
    agent_id: str = typer.Option(
        ..., help="Identifier for the agent, e.g. claude-payments (required)"
    ),
    feature_name: str = typer.Option(..., help="Human-readable feature name (required)"),
    schema_changes: str = typer.Option(..., help="DDL statements or path to SQL file (required)"),
    tables_affected: str | None = typer.Option(
        None, help="Comma-separated table names affected (default: none)"
    ),
    risk_level: str = typer.Option("low", help="Risk assessment: low, medium, high (default: low)"),
    estimated_hours: float = typer.Option(0, help="Estimated hours to complete (default: 0)"),
    database_url: str | None = typer.Option(None, help="Database URL (default: from config)"),
    metadata: str | None = typer.Option(None, help="JSON metadata string (default: none)"),
    format_output: str = typer.Option(
        "text", "--format", "-f", help="Output format: text or json (default: text)"
    ),
) -> None:
    """Register a new agent intention for schema changes.

    Example:
        confiture coordinate register \\
            --agent-id claude-payments \\
            --feature-name stripe_integration \\
            --schema-changes "ALTER TABLE users ADD COLUMN stripe_id TEXT" \\
            --tables-affected users \\
            --risk-level medium
    """
    try:
        conn = _get_connection(database_url)
        registry = IntentRegistry(conn)

        # Parse schema changes
        if schema_changes.endswith(".sql"):
            # Load from file
            schema_file = Path(schema_changes)
            if not schema_file.exists():
                console.print(f"[red]Error:[/red] SQL file not found: {schema_changes}")
                raise typer.Exit(1)
            schema_list = [schema_file.read_text()]
        else:
            # Split by semicolon
            schema_list = [s.strip() for s in schema_changes.split(";") if s.strip()]

        # Parse tables affected
        tables_list = []
        if tables_affected:
            tables_list = [t.strip() for t in tables_affected.split(",")]

        # Parse metadata
        meta_dict = {}
        if metadata:
            import json

            try:
                meta_dict = json.loads(metadata)
            except json.JSONDecodeError:
                console.print("[yellow]Warning:[/yellow] Invalid JSON metadata, ignoring")

        # Register intention
        intent = registry.register(
            agent_id=agent_id,
            feature_name=feature_name,
            schema_changes=schema_list,
            tables_affected=tables_list if tables_list else None,
            estimated_duration_ms=int(estimated_hours * 3600 * 1000) if estimated_hours else 0,
            risk_level=risk_level,
            metadata=meta_dict,
        )

        # Get conflicts
        conflicts = registry.get_conflicts(intent.id)

        # Display result
        if format_output == "json":
            output_data = {
                "intent": intent.to_dict(),
                "conflicts": [c.to_dict() for c in conflicts],
            }
            _output_json(output_data)
        else:
            # Text output
            table = Table(title="Intention Registered")
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="green")

            table.add_row("Intent ID", intent.id)
            table.add_row("Agent", agent_id)
            table.add_row("Feature", feature_name)
            table.add_row("Branch", intent.branch_name)
            table.add_row("Status", intent.status.value)
            table.add_row("Risk Level", intent.risk_level.value)
            table.add_row("Tables Affected", ", ".join(intent.tables_affected))

            console.print(table)

            # Show conflicts if any
            if conflicts:
                console.print(
                    f"\n[yellow]Warning:[/yellow] Found {len(conflicts)} conflict(s) with existing intentions:"
                )
                for conflict in conflicts:
                    console.print(
                        f"  - {conflict.conflict_type.value}: {', '.join(conflict.affected_objects)} "
                        f"[{conflict.severity.value}]"
                    )

        conn.close()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@coordinate_app.command()
def list_intents(
    status_filter: str | None = typer.Option(
        None,
        help="Filter by status (registered, in_progress, completed, merged, abandoned, conflicted)",
    ),
    agent_filter: str | None = typer.Option(None, help="Filter by agent ID"),
    database_url: str | None = typer.Option(None, help="Database URL"),
    format_output: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
) -> None:
    """List all registered intentions with optional filtering.

    Example:
        confiture coordinate list-intents --status-filter in_progress
        confiture coordinate list-intents --agent-filter claude-payments
    """
    try:
        conn = _get_connection(database_url)
        registry = IntentRegistry(conn)

        # Parse status filter
        intent_status = None
        if status_filter:
            try:
                intent_status = IntentStatus[status_filter.upper()]
            except KeyError:
                console.print(
                    f"[red]Error:[/red] Invalid status: {status_filter}. "
                    "Valid options: registered, in_progress, completed, merged, abandoned, conflicted"
                )
                raise typer.Exit(1) from None

        # List intents
        intents = registry.list_intents(status=intent_status, agent_id=agent_filter)

        if not intents:
            if format_output == "json":
                _output_json({"intents": []})
            else:
                console.print("[yellow]No intentions found matching filters[/yellow]")
            conn.close()
            return

        # Display results
        if format_output == "json":
            output_data = {
                "total": len(intents),
                "intents": [intent.to_dict() for intent in intents],
            }
            _output_json(output_data)
        else:
            table = Table(title=f"Intentions ({len(intents)} total)")
            table.add_column("ID", style="cyan", width=10)
            table.add_column("Agent", style="green")
            table.add_column("Feature", style="blue")
            table.add_column("Status", style="yellow")
            table.add_column("Risk", style="red")
            table.add_column("Tables", style="magenta")

            for intent in intents:
                table.add_row(
                    intent.id[:8],
                    intent.agent_id,
                    intent.feature_name,
                    intent.status.value,
                    intent.risk_level.value,
                    ", ".join(intent.tables_affected) if intent.tables_affected else "-",
                )

            console.print(table)
        conn.close()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@coordinate_app.command()
def check(
    agent_id: str = typer.Option(..., help="Agent ID"),
    feature_name: str = typer.Option(..., help="Feature name"),
    schema_changes: str = typer.Option(..., help="DDL statements or SQL file path"),
    tables_affected: str | None = typer.Option(None, help="Comma-separated table names"),
    database_url: str | None = typer.Option(None, help="Database URL"),
    format_output: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
) -> None:
    """Check for conflicts with a proposed set of schema changes.

    Example:
        confiture coordinate check \\
            --agent-id claude-auth \\
            --feature-name oauth2 \\
            --schema-changes "ALTER TABLE users ADD COLUMN oauth_provider TEXT" \\
            --tables-affected users
    """
    try:
        conn = _get_connection(database_url)
        registry = IntentRegistry(conn)

        # Parse schema changes
        if schema_changes.endswith(".sql"):
            schema_file = Path(schema_changes)
            if not schema_file.exists():
                console.print(f"[red]Error:[/red] SQL file not found: {schema_changes}")
                raise typer.Exit(1)
            schema_list = [schema_file.read_text()]
        else:
            schema_list = [s.strip() for s in schema_changes.split(";") if s.strip()]

        # Parse tables
        tables_list = []
        if tables_affected:
            tables_list = [t.strip() for t in tables_affected.split(",")]

        # Create a temporary intent for checking
        from uuid import uuid4

        from confiture.integrations.pggit.coordination import Intent

        temp_intent = Intent(
            id=str(uuid4()),
            agent_id=agent_id,
            feature_name=feature_name,
            branch_name=f"feature/{feature_name}",
            schema_changes=schema_list,
            tables_affected=tables_list if tables_list else [],
        )

        # Check existing intents
        existing = registry.list_intents(status=IntentStatus.REGISTERED)
        existing.extend(registry.list_intents(status=IntentStatus.IN_PROGRESS))

        # Detect conflicts
        detector = registry._detector
        all_conflicts = []

        for existing_intent in existing:
            conflicts = detector.detect_conflicts(temp_intent, existing_intent)
            all_conflicts.extend(conflicts)

        # Display results
        if format_output == "json":
            output_data = {
                "conflicts_detected": len(all_conflicts),
                "conflicts": [c.to_dict() for c in all_conflicts],
            }
            _output_json(output_data)
        else:
            if not all_conflicts:
                console.print("[green]✓ No conflicts detected![/green]")
            else:
                console.print(f"\n[red]✗ Found {len(all_conflicts)} conflict(s):[/red]\n")

                for conflict in all_conflicts:
                    console.print(f"  Type: [yellow]{conflict.conflict_type.value}[/yellow]")
                    console.print(f"  Severity: [red]{conflict.severity.value}[/red]")
                    console.print(f"  Affected: {', '.join(conflict.affected_objects)}")
                    console.print("  Suggestions:")
                    for suggestion in conflict.resolution_suggestions:
                        console.print(f"    - {suggestion}")
                    console.print()

        conn.close()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@coordinate_app.command()
def status(
    intent_id: str = typer.Option(..., help="Intention ID"),
    database_url: str | None = typer.Option(None, help="Database URL"),
    format_output: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
) -> None:
    """Show detailed status of a specific intention.

    Example:
        confiture coordinate status --intent-id 550e8400-e29b-41d4-a716-446655440000
    """
    try:
        conn = _get_connection(database_url)
        registry = IntentRegistry(conn)

        intent = registry.get_intent(intent_id)
        if not intent:
            if format_output == "json":
                _output_json({"error": "Intention not found", "intent_id": intent_id})
            else:
                console.print(f"[red]Error:[/red] Intention not found: {intent_id}")
            raise typer.Exit(1)

        # Get conflicts
        conflicts = registry.get_conflicts(intent.id)

        # Display intent details
        if format_output == "json":
            output_data = {
                "intent": intent.to_dict(),
                "conflicts": [c.to_dict() for c in conflicts],
            }
            _output_json(output_data)
        else:
            console.print(f"\n[cyan]Intention: {intent.feature_name}[/cyan]\n")

            table = Table(show_header=False, box=None)
            table.add_column(style="cyan")
            table.add_column(style="green")

            table.add_row("ID", intent.id)
            table.add_row("Agent", intent.agent_id)
            table.add_row("Feature", intent.feature_name)
            table.add_row("Branch", intent.branch_name)
            table.add_row("Status", intent.status.value)
            table.add_row("Risk Level", intent.risk_level.value)
            table.add_row("Created", str(intent.created_at))
            table.add_row("Updated", str(intent.updated_at))
            table.add_row(
                "Tables Affected",
                ", ".join(intent.tables_affected) if intent.tables_affected else "-",
            )

            console.print(table)

            # Show conflicts if any
            if conflicts:
                console.print(f"\n[yellow]{len(conflicts)} Conflict(s):[/yellow]\n")
                for i, conflict in enumerate(conflicts, 1):
                    console.print(
                        f"  {i}. {conflict.conflict_type.value} [{conflict.severity.value}] "
                        f"({', '.join(conflict.affected_objects)})"
                    )
                    if conflict.resolution_notes:
                        console.print(f"     Notes: {conflict.resolution_notes}")

        conn.close()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@coordinate_app.command()
def conflicts(
    database_url: str | None = typer.Option(None, help="Database URL"),
    format_output: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
) -> None:
    """List all detected conflicts between intentions.

    Example:
        confiture coordinate conflicts
    """
    try:
        conn = _get_connection(database_url)
        registry = IntentRegistry(conn)

        # Get all conflicted intents
        conflicted = registry.list_intents(status=IntentStatus.CONFLICTED)

        if not conflicted:
            if format_output == "json":
                _output_json({"conflicted_intents": []})
            else:
                console.print("[green]✓ No conflicts detected![/green]")
            conn.close()
            return

        # Gather all conflicts
        all_conflicts_data = []
        for intent in conflicted:
            intent_conflicts = registry.get_conflicts(intent.id)
            all_conflicts_data.append(
                {
                    "intent": intent.to_dict(),
                    "conflicts": [c.to_dict() for c in intent_conflicts],
                }
            )

        if format_output == "json":
            output_data = {
                "total_conflicted_intents": len(conflicted),
                "conflicted_intents": all_conflicts_data,
            }
            _output_json(output_data)
        else:
            console.print(f"\n[yellow]{len(conflicted)} Intention(s) with conflicts:[/yellow]\n")

            for intent in conflicted:
                console.print(f"  [cyan]{intent.feature_name}[/cyan] ({intent.agent_id})")

                # Get conflicts for this intent
                intent_conflicts = registry.get_conflicts(intent.id)
                for conflict in intent_conflicts:
                    severity_color = (
                        "red" if conflict.severity == ConflictSeverity.ERROR else "yellow"
                    )
                    open_tag = f"[{severity_color}]"
                    close_tag = f"[/{severity_color}]"
                    console.print(
                        f"    - {conflict.conflict_type.value} {open_tag}{conflict.severity.value}{close_tag} "
                        f"on {', '.join(conflict.affected_objects)}"
                    )

        conn.close()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@coordinate_app.command()
def resolve(
    conflict_id: int = typer.Option(..., help="Conflict ID"),
    notes: str = typer.Option(..., help="Resolution notes"),
    database_url: str | None = typer.Option(None, help="Database URL"),
    format_output: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
) -> None:
    """Mark a conflict as reviewed and provide resolution notes.

    Example:
        confiture coordinate resolve \\
            --conflict-id 42 \\
            --notes "Agents coordinated: applying changes sequentially"
    """
    try:
        conn = _get_connection(database_url)
        registry = IntentRegistry(conn)

        registry.resolve_conflict(conflict_id, reviewed=True, resolution_notes=notes)

        if format_output == "json":
            output_data = {
                "conflict_id": conflict_id,
                "resolved": True,
                "resolution_notes": notes,
            }
            _output_json(output_data)
        else:
            console.print(f"[green]✓ Conflict {conflict_id} marked as resolved[/green]")
            console.print(f"  Notes: {notes}")

        conn.close()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@coordinate_app.command()
def abandon(
    intent_id: str = typer.Option(..., help="Intention ID"),
    reason: str = typer.Option(..., help="Reason for abandonment"),
    database_url: str | None = typer.Option(None, help="Database URL"),
    format_output: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
) -> None:
    """Abandon an intention before completion.

    Example:
        confiture coordinate abandon \\
            --intent-id 550e8400-e29b-41d4-a716-446655440000 \\
            --reason "Feature cancelled by product team"
    """
    try:
        conn = _get_connection(database_url)
        registry = IntentRegistry(conn)

        intent = registry.get_intent(intent_id)
        if not intent:
            console.print(f"[red]Error:[/red] Intention not found: {intent_id}")
            raise typer.Exit(1)

        registry.mark_abandoned(intent_id, reason=reason)

        if format_output == "json":
            # Get updated intent to reflect new status
            updated_intent = registry.get_intent(intent_id)
            output_data = {
                "intent_id": intent_id,
                "feature_name": intent.feature_name,
                "status": updated_intent.status.value if updated_intent else "abandoned",
                "reason": reason,
            }
            _output_json(output_data)
        else:
            console.print("[green]✓ Intention abandoned[/green]")
            console.print(f"  Feature: {intent.feature_name}")
            console.print(f"  Reason: {reason}")

        conn.close()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
