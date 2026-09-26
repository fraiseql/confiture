"""What a Rich console prints as data, and what it prints as confiture's own markup.

Rich reads ``[...]`` in a printed string as a style tag: a value interpolated into
``console.print(f"…")`` that holds ``[tree_001]``, ``int[]`` or a path such as
``db/[legacy]/x.sql`` is swallowed, or restyles the line, or raises
``MarkupError``. Every value a console f-string interpolates is therefore
:func:`verbatim`, or :func:`markup` when it is markup confiture built itself;
``tests/unit/test_cli_prints_data_verbatim.py`` fails on one that is neither.
"""

from __future__ import annotations

from rich.markup import escape

from confiture.url_redaction import redact_credentials_in


def verbatim(value: object, spec: str = "") -> str:
    """*value* formatted with *spec*, escaped so Rich prints every character of it.

    Every credential in it is masked first (``postgresql://u:***@h``,
    ``password=***``): this is how every value reaches the console, so a
    message that carries a DSN prints it without its password.
    """
    return escape(redact_credentials_in(format(value, spec)))


def markup(value: str) -> str:
    """*value* unchanged: markup confiture built itself (``"[green]✓[/green]"``), to be rendered."""
    return value
