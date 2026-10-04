"""Formatter for the confiture diff command output."""

from confiture.cli.markup import Printer, markup
from confiture.models.results import DiffResult

#: The colour of a change's line, by the verb its wire type starts with.
_COLOURS: dict[str, str] = {"ADD": "green", "DROP": "red"}


def print_diff_text(result: DiffResult, console: Printer) -> None:
    """Print a human-readable diff to the given console."""
    if not result.has_changes:
        console.print("[green]No changes detected.[/green]")
        return

    n = len(result.changes)
    console.print(t"[cyan]{n} change{'s' if n != 1 else ''} detected:[/cyan]\n")

    for change in result.changes:
        verb, _, _ = change.type.partition("_")
        colour = _COLOURS.get(verb, "yellow")
        console.print(t"  [{markup(colour)}]{change}[/{markup(colour)}]")
