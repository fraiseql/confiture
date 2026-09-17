"""Shared CLI option factories and the option aliases more than one command takes.

``format_option`` is the one ``--format`` validator: an invalid value exits 5
with the error on stderr — the same way on every command — before the command
body runs, so nothing is printed to stdout and no database is touched.

An option two commands take is declared **once**, here. ``--schemas`` was
declared twice — in ``migrate validate`` and in ``migrate fix-signatures`` — and
the two help strings had already drifted apart before one of them changed its
default (#303). The second of those commands executes ``DROP FUNCTION``.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from confiture.cli.error_json import fail
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


#: ``--schemas`` for the signature checks. ``None`` means "each reader's own
#: default": the schemas the parsed source declares for ``--check-signatures``
#: and ``migrate fix-signatures``, and ``public`` for the three other checks that
#: read this option (#303).
CheckSignatureSchemasOpt = Annotated[
    str | None,
    typer.Option(
        "--schemas",
        help="Comma-separated list of schemas to inspect. Defaults to the schemas "
        "the source declares, which is what --check-live-drift derives from the "
        "same DDL.",
    ),
]
