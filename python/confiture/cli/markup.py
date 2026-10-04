"""What confiture prints as data, and what it prints as its own markup.

Rich reads ``[...]`` in a printed string as a style tag: a value interpolated into
``console.print(f"…")`` that holds ``[tree_001]``, ``int[]`` or a path such as
``db/[legacy]/x.sql`` is swallowed, or restyles the line, or raises
``MarkupError``. A template string separates the two by construction: its literal
text is confiture's markup, and :func:`render` writes every interpolation as
:func:`verbatim` does, unless it is a :class:`Markup` confiture built.
:class:`Printer` prints templates, literals and Rich renderables — never a
computed ``str`` — and holds the Rich console it prints through.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from string.templatelib import Interpolation, Template
from typing import Any, LiteralString, Self

from rich.console import (
    Console,
    ConsoleOptions,
    ConsoleRenderable,
    JustifyMethod,
    RenderableType,
    RenderResult,
)
from rich.markup import escape
from rich.measure import Measurement
from rich.style import Style
from rich.table import Table as _RichTable
from rich.text import Text

from confiture.url_redaction import redact_credentials_in

#: Control characters a printed value keeps: they lay text out and command nothing.
_LAYOUT = frozenset("\n\t")


def verbatim(value: object, spec: str = "") -> str:
    """*value* formatted with *spec*, escaped so Rich prints every character of it.

    Every credential in it is masked first (``postgresql://u:***@h``,
    ``password=***``): this is how every value reaches the console, so a
    message that carries a DSN prints it without its password. A control
    character is written as its escape (``\\x1b``), so a value — a quoted
    identifier can hold an ESC — never sends the terminal a command.
    """
    return escape(_shown(format(value, spec)))


def verbatim_text(value: object) -> Text:
    """*value* as a Rich :class:`~rich.text.Text`, for a table cell: :func:`verbatim`'s rules."""
    return Text(_shown(str(value)))


def _shown(text: str) -> str:
    """*text* with its credentials masked and each control character but a newline or tab escaped."""
    return "".join(
        c if c in _LAYOUT or unicodedata.category(c) != "Cc" else repr(c)[1:-1]
        for c in redact_credentials_in(text)
    )


class Markup(str):
    """Markup confiture built itself (``"[green]✓[/green]"``): rendered, never escaped."""

    __slots__ = ()


def markup(value: str) -> Markup:
    """*value* as :class:`Markup`: confiture's own markup, to be rendered as written."""
    return Markup(value)


_CONVERSIONS: dict[str, Callable[[object], str]] = {"r": repr, "s": str, "a": ascii}


def _interpolated(item: Interpolation) -> str:
    value = item.value
    if item.conversion is not None:
        value = _CONVERSIONS[item.conversion](value)
    elif isinstance(value, Markup) and not item.format_spec:
        return value
    return verbatim(value, item.format_spec)


def render(template: Template) -> str:
    """*template* as Rich markup: its text as written, each interpolation as data.

    An interpolation is converted (``!r``/``!s``/``!a``), formatted with its spec
    and escaped exactly as :func:`verbatim` does — unless its value is a
    :class:`Markup`, which is written as is.
    """
    return "".join(part if isinstance(part, str) else _interpolated(part) for part in template)


#: What a printer prints: a literal (confiture's markup), a template, or a renderable.
type Printable = LiteralString | Template | ConsoleRenderable


def _renderable(item: Printable) -> RenderableType:
    return render(item) if isinstance(item, Template) else item


#: What a table cell holds: a literal, a template, or text that is data.
type Cell = LiteralString | Template | Text | None


class Table:
    """A Rich table whose cells are templates: a value in a cell is data.

    Composition, like :class:`Printer`: a subclass of Rich's table would accept
    any ``str`` cell as markup to whoever holds it as one.
    """

    def __init__(self, *headers: LiteralString, **options: Any) -> None:
        self._table = _RichTable(*headers, **options)

    def add_column(self, header: LiteralString = "", **options: Any) -> None:
        self._table.add_column(header, **options)

    def add_row(
        self, *cells: Cell, style: str | Style | None = None, end_section: bool = False
    ) -> None:
        """Add a row; a template cell is rendered, its interpolations data."""
        self._table.add_row(
            *(render(c) if isinstance(c, Template) else c for c in cells),
            style=style,
            end_section=end_section,
        )

    def add_section(self) -> None:
        self._table.add_section()

    @property
    def row_count(self) -> int:
        return self._table.row_count

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self._table

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement.get(console, options, self._table)


class Printer:
    """Where confiture prints: templates, literals and renderables, through one Rich console.

    Built by composition, so nothing that holds a printer reaches Rich's own
    ``print``, which takes any ``str`` as markup. :attr:`rich` is the console
    itself, for a Rich object that draws (``Progress``, ``Live``); it is passed,
    never printed through.
    """

    def __init__(self, console: Console) -> None:
        self._console = console

    @classmethod
    def stdout(cls) -> Self:
        return cls(Console())

    @classmethod
    def stderr(cls) -> Self:
        return cls(Console(stderr=True))

    @classmethod
    def recording(cls, *, width: int = 120) -> Self:
        """A printer whose output :meth:`export_text` returns, as plain text."""
        return cls(Console(record=True, width=width, color_system=None, force_terminal=False))

    @classmethod
    def quiet(cls) -> Self:
        return cls(Console(quiet=True))

    @property
    def rich(self) -> Console:
        """The Rich console behind this printer, to hand to a Rich object that draws."""
        return self._console

    def print(
        self,
        *objects: Printable,
        end: str = "\n",
        style: str | Style | None = None,
        justify: JustifyMethod | None = None,
        soft_wrap: bool | None = None,
        highlight: bool | None = None,
    ) -> None:
        """Print *objects*, each template rendered: its interpolations are data."""
        self._console.print(
            *(_renderable(o) for o in objects),
            end=end,
            style=style,
            justify=justify,
            soft_wrap=soft_wrap,
            highlight=highlight,
        )

    def export_text(self) -> str:
        """What a :meth:`recording` printer printed, as plain text."""
        return self._console.export_text()
