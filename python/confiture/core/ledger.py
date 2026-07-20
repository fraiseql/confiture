"""Migration ledger existence probe.

The migration ledger (``tb_confiture`` by default, configurable via
``tracking_table``) records which migrations have been applied.  Commands that
read it need to distinguish *absent* from *empty*: a database built from schema
files has no ledger at all, which is a different state from a database that has
one with no rows in it.

This module holds the single implementation of that check, callable with a raw
connection so that callers which never build a :class:`Migrator` — such as
``verify-checksums`` — do not have to reach into ``core._migrator``.

Caveat: for a bare (unqualified) table name the probe matches the table in
*any* schema, and respects neither ``search_path`` nor schema privileges.
``to_regclass('tb_confiture') IS NOT NULL`` would be strictly more correct, but
switching to it changes behaviour for ``migrate status``,
``migrate up --auto-baseline`` and ``MigratorSession.current()``, so it is
tracked as a follow-up rather than changed here.
"""

from __future__ import annotations

from typing import Any

_QUALIFIED_SQL = """
    SELECT EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
    )
"""

_BARE_SQL = """
    SELECT EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_name = %s
    )
"""


def ledger_exists(connection: Any, table: str) -> bool:
    """Return True when the migration ledger table exists.

    Args:
        connection: An open DB-API connection (psycopg3).
        table: Bare (``tb_confiture``) or schema-qualified
            (``public.tb_confiture``) table name.  A qualified name filters on
            the schema; a bare name matches the table in any schema.

    Returns:
        True if the table is present, False otherwise.

    Example:
        >>> ledger_exists(conn, "tb_confiture")
        False
    """
    schema, _, base = table.partition(".")
    if base:
        sql, params = _QUALIFIED_SQL, (schema, base)
    else:
        sql, params = _BARE_SQL, (schema,)

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return bool(row[0]) if row else False
