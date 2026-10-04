"""The text of a statement confiture executes, for a message, a log line or a payload.

A statement reaches ``execute`` as a template string, a ``psycopg.sql`` composition
or a plain string. Only psycopg knows how the first two render — a ``Template`` has
no ``as_string`` of its own — so every place that shows a statement asks here.
"""

from contextlib import suppress
from string.templatelib import Template
from typing import Any

import psycopg
from psycopg import sql
from psycopg.abc import AdaptContext


def rendered(query: Any, context: AdaptContext | None = None) -> str:
    """*query* as the SQL text psycopg sends for it.

    Args:
        query: A ``Template``, a ``psycopg.sql.Composable`` or anything else
            (shown with ``str``).
        context: A connection or cursor, when one is at hand: some adapters
            render only through one.
    """
    if not isinstance(query, (Template, sql.Composable)):
        return str(query)
    if context is not None:
        # A context psycopg cannot adapt through (a closed or stand-in connection)
        # still renders unbound.
        with suppress(psycopg.Error, TypeError):
            return sql.as_string(query, context)
    return sql.as_string(query)
