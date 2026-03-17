"""Formatter for the confiture diff command output."""

from rich.console import Console

from confiture.models.results import DiffResult  # noqa: TCH001

_ADD_TYPES = frozenset(
    {
        "ADD_TABLE",
        "ADD_COLUMN",
        "ADD_INDEX",
        "ADD_FOREIGN_KEY",
        "ADD_CHECK_CONSTRAINT",
        "ADD_UNIQUE_CONSTRAINT",
        "ADD_ENUM_TYPE",
        "ADD_SEQUENCE",
    }
)
_DROP_TYPES = frozenset(
    {
        "DROP_TABLE",
        "DROP_COLUMN",
        "DROP_INDEX",
        "DROP_FOREIGN_KEY",
        "DROP_CHECK_CONSTRAINT",
        "DROP_UNIQUE_CONSTRAINT",
        "DROP_ENUM_TYPE",
        "DROP_SEQUENCE",
    }
)


def print_diff_text(result: DiffResult, console: Console) -> None:
    """Print a human-readable diff to the given console."""
    if not result.has_changes:
        console.print("[green]No changes detected.[/green]")
        return

    n = len(result.changes)
    console.print(f"[cyan]{n} change{'s' if n != 1 else ''} detected:[/cyan]\n")

    for change in result.changes:
        change_type = change.type
        if change_type in _ADD_TYPES:
            colour = "green"
        elif change_type in _DROP_TYPES:
            colour = "red"
        else:
            colour = "yellow"
        console.print(f"  [{colour}]{change}[/{colour}]")
