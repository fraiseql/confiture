"""Shared identifier-quoting helpers for suggestion templates.

Templates take :class:`~confiture.core.idempotency._captures.Captures`
and assemble SQL. These helpers handle the awkward bits — quoting an
identifier only when it actually needs quoting, joining ``schema.name``
when ``schema`` is present.
"""

from __future__ import annotations

import keyword
import re

_BARE_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def quote_ident(name: str) -> str:
    """Quote ``name`` as a PostgreSQL identifier when needed.

    Lowercase ASCII identifiers that aren't reserved keywords are emitted
    bare; anything else gets double-quoted with internal quotes doubled.
    """
    if _BARE_IDENT_RE.match(name) and not keyword.iskeyword(name):
        return name
    return '"' + name.replace('"', '""') + '"'


def qualify(schema: str | None, name: str | None) -> str | None:
    """Render ``schema.name`` (or ``name`` alone), quoting both halves.

    Returns ``None`` when ``name`` is missing — the caller is responsible
    for the missing-identifier fallback.
    """
    if not name:
        return None
    qname = quote_ident(name)
    if schema:
        return f"{quote_ident(schema)}.{qname}"
    return qname
