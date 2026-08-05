"""Migration ledger existence probe.

The migration ledger (``tb_confiture`` by default, configurable via
``tracking_table``) records which migrations have been applied.  Commands that
read it need to distinguish *absent* from *empty*: a database built from schema
files has no ledger at all, which is a different state from a database that has
one with no rows in it.

This module holds the single implementation of that check, callable with a raw
connection so that callers which never build a :class:`Migrator` — such as
``verify-checksums`` — do not have to reach into ``core._migrator``.

**The two paths are deliberately different queries** (#188).

A *bare* name resolves through ``search_path``, exactly as the query the probe
is a precondition for will.  Before 0.41.0 it matched
``information_schema.tables WHERE table_name = %s``, which is schema-blind: a
ledger in ``staging`` reported present to a session that would go on to read
``public``, and the two disagreed silently.

A *qualified* name stays on ``information_schema``.  Converting it too would be
tidier and is wrong: ``to_regclass('hidden.tb_secret')`` **raises**
``permission denied for schema hidden`` for a role without ``USAGE``, where the
``information_schema`` query returns cleanly (both measured on PostgreSQL 17.8).
A qualified name already filters on schema correctly, so the conversion would
buy nothing and would put an unhandled psycopg exception on the hot ledger path
— the crash class #182 and 0.37.0 closed.

The asymmetry is the point, not an oversight.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from confiture.exceptions import SQLError

_QUALIFIED_SQL = """
    SELECT EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
    )
"""

# `to_regclass` resolves *any* relation kind, so a sequence or an index named
# `tb_confiture` would answer "the ledger exists".  The relkinds below are the
# ones `information_schema.tables` reported — ordinary and partitioned tables,
# views, foreign tables — so the only behaviour this conversion changes is
# search_path awareness.
_BARE_SQL = """
    SELECT n.nspname, c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.oid = to_regclass(%s)
      AND c.relkind IN ('r', 'p', 'v', 'f')
"""

# Schema-blind on purpose: this answers "does this name exist anywhere?", the
# question `LedgerProbe` deliberately stopped answering.  `pg_class` rather than
# `information_schema` so it does not depend on table privileges.
_ANYWHERE_SQL = """
    SELECT n.nspname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relname = %s
      AND c.relkind IN ('r', 'p', 'v', 'f')
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY n.nspname
"""


@dataclass(frozen=True)
class LedgerProbe:
    """The answer to "is the ledger there, and which one did I find?".

    Attributes:
        exists: Whether a ledger relation resolves for this session.
        resolved_name: The schema-qualified relation the name resolved to, or
            ``None`` when it did not resolve.  For a bare name this is the
            probe's real value: it lets a command report *reading
            ``staging.tb_confiture``* instead of leaving the operator to guess
            which of two same-named tables the session picked.

    Note:
        ``exists`` is presence, not readability.  A role that can see a table
        in ``information_schema`` but cannot ``SELECT`` from it gets
        ``exists=True``.  Readability was considered and dropped: the obvious
        implementation, ``has_table_privilege``, raises on exactly the
        missing-``USAGE`` case that motivates the question.
    """

    exists: bool
    resolved_name: str | None = None


def probe_ledger(connection: Any, table: str) -> LedgerProbe:
    """Resolve the migration ledger for this session.

    Args:
        connection: An open DB-API connection (psycopg3).
        table: Bare (``tb_confiture``) or schema-qualified
            (``public.tb_confiture``) table name.  A bare name resolves through
            ``search_path``; a qualified name filters on the schema it names.

    Returns:
        A :class:`LedgerProbe` carrying presence and the resolved relation.

    Raises:
        SQLError: The bare-name probe was refused for lack of privilege.  Raw
            psycopg exceptions never escape this function.

    Example:
        >>> probe_ledger(conn, "tb_confiture")
        LedgerProbe(exists=True, resolved_name='public.tb_confiture')
    """
    schema, _, base = table.partition(".")
    if base:
        return _probe_qualified(connection, schema, base)
    return _probe_bare(connection, schema)


def ledger_exists(connection: Any, table: str) -> bool:
    """Return True when the migration ledger table exists.

    The boolean face of :func:`probe_ledger`, kept so callers that only need a
    yes/no need not unpack a dataclass.

    Args:
        connection: An open DB-API connection (psycopg3).
        table: Bare or schema-qualified table name.

    Returns:
        True if the ledger is present, False otherwise.

    Example:
        >>> ledger_exists(conn, "tb_confiture")
        False
    """
    return probe_ledger(connection, table).exists


def find_ledger_relations(connection: Any, table: str) -> list[str]:
    """Every schema holding a relation of this name, qualified, sorted.

    Schema-blind by design — it is the sweep that turns "the ledger did not
    resolve" into "…but there is one in ``staging``", which is the difference
    between ``migrate up --auto-detect-baseline`` refusing and it quietly
    building a second ledger.  A qualified *table* is swept by its base name,
    since the whole point is to find copies outside the named schema.

    Args:
        connection: An open DB-API connection (psycopg3).
        table: Bare or schema-qualified table name.

    Returns:
        ``["archive.tb_confiture", "staging.tb_confiture"]``-style names, empty
        when the name is unused.
    """
    base = table.rpartition(".")[2]
    with connection.cursor() as cursor:
        cursor.execute(_ANYWHERE_SQL, (base,))
        return [f"{row[0]}.{base}" for row in cursor.fetchall()]


def _probe_qualified(connection: Any, schema: str, base: str) -> LedgerProbe:
    with connection.cursor() as cursor:
        cursor.execute(_QUALIFIED_SQL, (schema, base))
        row = cursor.fetchone()
    if not (row and row[0]):
        return LedgerProbe(exists=False)
    return LedgerProbe(exists=True, resolved_name=f"{schema}.{base}")


def _probe_bare(connection: Any, name: str) -> LedgerProbe:
    try:
        with connection.cursor() as cursor:
            cursor.execute(_BARE_SQL, (name,))
            row = cursor.fetchone()
    except psycopg.errors.InsufficientPrivilege as e:
        # Narrow on purpose.  A bare name cannot reach the missing-USAGE case
        # (search_path silently skips schemas the role cannot use), so this
        # covers the residue — EXECUTE revoked on `to_regclass`, say.  Catching
        # anything broader here would swallow real defects in this module.
        raise SQLError(
            _BARE_SQL,
            (name,),
            e,
            resolution_hint=(
                f"The current role may not resolve {name!r}. Grant it the "
                "privileges the migration ledger needs, or connect as the role "
                "that owns it."
            ),
        ) from e
    if not row:
        return LedgerProbe(exists=False)
    return LedgerProbe(exists=True, resolved_name=f"{row[0]}.{row[1]}")
