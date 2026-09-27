"""What a Rich console prints as data, and what it prints as confiture's own markup.

Rich reads ``[...]`` in a printed string as a style tag: a value interpolated into
``console.print(f"…")`` that holds ``[tree_001]``, ``int[]`` or a path such as
``db/[legacy]/x.sql`` is swallowed, or restyles the line, or raises
``MarkupError``. Every value a console f-string interpolates is therefore
:func:`verbatim`, or :func:`markup` when it is markup confiture built itself;
``tests/unit/test_cli_prints_data_verbatim.py`` fails on one that is neither.
"""

from __future__ import annotations

import unicodedata

from rich.markup import escape
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


def markup(value: str) -> str:
    """*value* unchanged: markup confiture built itself (``"[green]✓[/green]"``), to be rendered."""
    return value
