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

import re
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql as pgsql

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

    The name is split exactly as :func:`probe_ledger` splits it — on the *first*
    dot.  The two have to agree: this function's answer is only meaningful as a
    follow-up to that one, and a sweep for a different relation than the one
    probed would report look-alikes that are not look-alikes at all.

    Args:
        connection: An open DB-API connection (psycopg3).
        table: Bare or schema-qualified table name.

    Returns:
        ``["archive.tb_confiture", "staging.tb_confiture"]``-style names, empty
        when the name is unused.
    """
    schema, _, qualified_base = table.partition(".")
    base = qualified_base or schema
    with connection.cursor() as cursor:
        cursor.execute(_ANYWHERE_SQL, (base,))
        return [f"{row[0]}.{base}" for row in cursor.fetchall()]


def notable_resolution(configured: str, resolved: str | None) -> str | None:
    """The resolved name, but only when it is worth telling the operator.

    Two resolutions carry no information: the one that matches what they
    configured, and a bare name landing in ``public``, which is the documented
    default. Printing either on every run would bury the case that *does*
    matter — a bare name resolving somewhere unexpected — in noise.

    Args:
        configured: The ``tracking_table`` value as written in config.
        resolved: :attr:`LedgerProbe.resolved_name`, or None.

    Returns:
        The resolved name when it is neither the configured name nor its
        ``public`` default, else None.
    """
    if resolved is None or resolved in (configured, f"public.{configured}"):
        return None
    return resolved


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


# ---------------------------------------------------------------------------
# The name as an identifier
# ---------------------------------------------------------------------------
#
# ``tracking_table`` is configuration, and configuration is text that anyone
# with write access to the repository controls.  Everything that turns the name
# into SQL goes through the three functions below so the rule is stated once:
# the name must be a plain, optionally schema-qualified identifier, and it
# reaches the server only as a :class:`psycopg.sql.Identifier` — never spliced
# into a query string by hand.

# Allows 'table_name' or 'schema.table_name' (letters, digits, underscores only).
VALID_TABLE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?$")

# PostgreSQL reserved words that must never be used as bare table names.
# pgsql.Identifier quotes them correctly in SQL, but they would confuse anyone
# writing ad-hoc queries against the tracking table.
POSTGRES_RESERVED_WORDS = frozenset(
    {
        "all",
        "analyse",
        "analyze",
        "and",
        "any",
        "array",
        "as",
        "asc",
        "asymmetric",
        "both",
        "case",
        "cast",
        "check",
        "collate",
        "column",
        "constraint",
        "create",
        "cross",
        "current_catalog",
        "current_date",
        "current_role",
        "current_schema",
        "current_time",
        "current_timestamp",
        "current_user",
        "default",
        "deferrable",
        "desc",
        "distinct",
        "do",
        "else",
        "end",
        "except",
        "false",
        "fetch",
        "for",
        "foreign",
        "from",
        "full",
        "grant",
        "group",
        "having",
        "ilike",
        "in",
        "initially",
        "inner",
        "intersect",
        "into",
        "is",
        "isnull",
        "join",
        "lateral",
        "leading",
        "left",
        "like",
        "limit",
        "localtime",
        "localtimestamp",
        "natural",
        "not",
        "notnull",
        "null",
        "offset",
        "on",
        "only",
        "or",
        "order",
        "outer",
        "overlaps",
        "placing",
        "primary",
        "references",
        "returning",
        "right",
        "row",
        "select",
        "session_user",
        "similar",
        "some",
        "symmetric",
        "table",
        "tablesample",
        "then",
        "to",
        "trailing",
        "true",
        "union",
        "unique",
        "user",
        "using",
        "variadic",
        "verbose",
        "when",
        "where",
        "window",
        "with",
    }
)


def validate_table_name(name: str) -> str:
    """Return *name* when it is a usable tracking-table name.

    The one rule every reader of ``tracking_table`` applies — ``Migrator``,
    the checksum verifier, the CLI.  Applying it in one place is what lets the
    others build SQL from the name without re-checking it.

    Args:
        name: Bare (``tb_confiture``) or schema-qualified (``public.tb_confiture``).

    Returns:
        *name*, unchanged.

    Raises:
        ValueError: The name is not letters, digits and underscores in at most
            two dot-separated parts, or its table part is a PostgreSQL reserved
            word.
    """
    if not VALID_TABLE_RE.match(name):
        raise ValueError(
            f"Invalid migration_table name: {name!r}. "
            "Use letters, digits, and underscores only, optionally "
            "schema-qualified (e.g. 'public.tb_confiture')."
        )
    _, base = split_qualified_table(name)
    if base.lower() in POSTGRES_RESERVED_WORDS:
        raise ValueError(
            f"Migration table name {name!r} is a PostgreSQL reserved word. "
            "Choose a descriptive name like 'tb_confiture' or 'schema_migrations'."
        )
    return name


def split_qualified_table(name: str) -> tuple[str | None, str]:
    """Split ``schema.table`` into ``(schema, table)``; a bare name gives ``(None, name)``.

    Splits on the *first* dot, exactly as :func:`probe_ledger` does, so every
    reader of the name agrees on which relation it denotes.

    Args:
        name: Bare or schema-qualified table name.

    Returns:
        The schema (or ``None``) and the table part.

    Example:
        >>> split_qualified_table("public.tb_confiture")
        ('public', 'tb_confiture')
        >>> split_qualified_table("tb_confiture")
        (None, 'tb_confiture')
    """
    schema, dot, base = name.partition(".")
    if not dot:
        return None, name
    return schema, base


def table_identifier(name: str) -> pgsql.Identifier:
    """The tracking table as a quoted identifier for ``sql.SQL(...).format``.

    A bare name becomes a single-part identifier and resolves through
    ``search_path`` at execution time — the same resolution :func:`probe_ledger`
    gives it, so the existence check and the query that follows it talk about
    one table.  Nothing here defaults a bare name to ``public``.

    Args:
        name: Bare or schema-qualified table name.

    Returns:
        ``Identifier(table)`` or ``Identifier(schema, table)``.
    """
    schema, base = split_qualified_table(name)
    if schema is None:
        return pgsql.Identifier(base)
    return pgsql.Identifier(schema, base)
