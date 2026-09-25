"""Shared identifier-quoting helpers for suggestion templates.

Templates take :class:`~confiture.core.idempotency._captures.Captures`
and assemble SQL. :func:`qualify` joins ``schema.name`` when ``schema`` is
present, each half quoted by the one identifier quoter
(:func:`confiture.core.schema_identity.quote_identifier`).
"""

from __future__ import annotations

from confiture.core.schema_identity import quote_identifier


def qualify(schema: str | None, name: str | None) -> str | None:
    """Render ``schema.name`` (or ``name`` alone), quoting both halves.

    Returns ``None`` when ``name`` is missing — the caller is responsible
    for the missing-identifier fallback.
    """
    if not name:
        return None
    qname = quote_identifier(name)
    if schema:
        return f"{quote_identifier(schema)}.{qname}"
    return qname
