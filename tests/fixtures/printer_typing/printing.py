"""What ty accepts from a printer, and the one call it refuses (line 13)."""

from rich.text import Text

from confiture.cli.markup import Printer


def show(out: Printer, name: str) -> None:
    out.print("[green]a literal is confiture's markup[/green]")
    out.print(t"[bold]{name}[/bold] is data")
    out.print(Text(name))
    out.print(Text(name), t"{name}", "literal")
    out.print(name)
