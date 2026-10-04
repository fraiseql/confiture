"""A value printed through confiture's printer is data by construction (#600).

``render(t"…")`` writes a template's literal text as confiture's markup and each
interpolation exactly as ``verbatim`` writes it — credentials masked, control
characters escaped, brackets escaped — unless the value is a ``Markup``
confiture built. The ``Printer`` prints templates and nothing computed: what a
recording Rich console printed for ``f"…{verbatim(v)}…"`` it prints for
``t"…{v}…"``.
"""

from pathlib import Path

import pytest
from rich.console import Console
from rich.text import Text

from confiture.cli.markup import Markup, Printer, Table, markup, render, verbatim

ESC = "\x1b[31mred"
VALUES = [
    ("[tree_001]", ""),
    ("int[]", ""),
    ("db/[legacy]/x.sql", ""),
    (ESC, ""),
    ("postgresql://app:s3cret@db/prod", ""),
    (3.14159, ".2f"),
    (1234567, ","),
    (None, ""),
    (Path("db/[x]/y.sql"), ""),
]


@pytest.mark.parametrize(("value", "spec"), VALUES)
def test_an_interpolation_renders_as_verbatim(value: object, spec: str) -> None:
    assert render(t"[red]{value:{spec}}[/red]") == f"[red]{verbatim(value, spec)}[/red]"


@pytest.mark.parametrize(("value", "spec"), VALUES)
def test_a_conversion_applies_before_the_escape(value: object, spec: str) -> None:
    assert render(t"{value!r}") == verbatim(repr(value))


def test_markup_confiture_built_is_rendered_as_markup() -> None:
    tag = markup("[green]✓[/green]")
    assert isinstance(tag, Markup)
    assert render(t"{tag} done") == "[green]✓[/green] done"


def test_a_style_in_a_tag_position_is_markup() -> None:
    color = markup("yellow")
    assert render(t"[{color}]x[/{color}]") == "[yellow]x[/yellow]"


def _recorded(print_: object) -> str:
    console = Console(record=True, width=200, color_system=None, force_terminal=False)
    print_(console)
    return console.export_text()


@pytest.mark.parametrize(("value", "spec"), VALUES)
def test_the_printer_prints_what_a_console_printed(value: object, spec: str) -> None:
    printer = Printer.recording(width=200)
    printer.print(t"[bold]{value:{spec}}[/bold] tail", end="!\n")
    expected = _recorded(lambda c: c.print(f"[bold]{verbatim(value, spec)}[/bold] tail", end="!\n"))
    assert printer.export_text() == expected


def test_the_printer_passes_its_keywords_through() -> None:
    printer = Printer.recording(width=40)
    printer.print("[red]a[/red]", "b", style="bold", soft_wrap=True, highlight=False)
    printer.print(Text("[kept]"))
    assert printer.export_text() == "a b\n[kept]\n"


def test_a_table_cell_is_data() -> None:
    printer = Printer.recording(width=60)
    table = Table("name", "type")
    name = "[tree_001]"
    table.add_row(t"{name}", Text("int[]"))
    table.add_row("[bold]literal[/bold]", t"{markup('[red]x[/red]')}")
    printer.print(table)
    shown = printer.export_text()
    assert "[tree_001]" in shown and "int[]" in shown
    assert "literal" in shown and "[bold]" not in shown and "[red]" not in shown


def test_a_quiet_printer_prints_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    Printer.quiet().print("[red]nothing[/red]")
    assert capsys.readouterr() == ("", "")


def test_rich_objects_get_the_console_behind_the_printer() -> None:
    printer = Printer.stderr()
    assert isinstance(printer.rich, Console)
    assert printer.rich.stderr
