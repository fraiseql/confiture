"""Shared CLI option factories (ARC-02).

``format_option`` is the one ``--format`` validator: an invalid value exits 5
with the error on stderr — the same way on every command — before the command
body runs, so nothing is printed to stdout and no database is touched.
"""

from __future__ import annotations

from typing import Any

import typer

from confiture.exceptions import ValidationError


def format_option(*allowed: str, default: str | None = None, help: str | None = None) -> Any:
    """``--format/-f`` restricted to *allowed*; the first value is the default.

    Example:
        >>> format_output: str = format_option("text", "json")
    """
    if not allowed:
        raise ValueError("format_option needs at least one allowed value")
    chosen_default = default if default is not None else allowed[0]
    if chosen_default not in allowed:
        raise ValueError(f"default {chosen_default!r} is not one of {allowed}")
    choices = ", ".join(f"'{value}'" for value in allowed)

    def _validate(value: str) -> str:
        if value not in allowed:
            from confiture.cli.error_json import fail

            fail(
                ValidationError(
                    f"Invalid --format {value!r}: use {choices}.",
                    context={"format": value, "allowed": list(allowed)},
                ),
                json_mode=False,
            )
        return value

    return typer.Option(
        chosen_default,
        "--format",
        "-f",
        callback=_validate,
        help=help or f"Output format: {' or '.join(allowed)} (default: {chosen_default})",
    )
