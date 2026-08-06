"""What a live database can tell preflight that migration files cannot (issue #199).

Preflight is a filesystem-only check by design, and that stays the primary path:
everything here is **strictly additive**. Two facts are worth a connection when
one is already open, because neither is recoverable from the migration SQL:

* **The current column type.** ``ALTER TABLE … ALTER COLUMN … TYPE bigint`` names
  the target and never the source, so without the database confiture cannot tell
  a widening from a narrowing — and so, honestly, emits no risk tier at all.
* **The server version.** Two rows of the lock table changed with a PostgreSQL
  release. Knowing the version turns the conservative reading into the true one.

Collection never raises: a database that refuses the introspection query yields
empty facts, and every consumer degrades to the static answer. Losing the
refinement is acceptable; failing a preflight because of it is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["SchemaFacts", "collect_schema_facts"]

# Columns of interest live in user schemas; the catalogs never do.
_COLUMN_TYPE_SQL = """
SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod)
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE a.attnum > 0
  AND NOT a.attisdropped
  AND c.relkind IN ('r', 'p', 'm', 'v', 'f')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
"""


@dataclass(frozen=True)
class SchemaFacts:
    """Facts read from a live database, all optional.

    An empty instance is the "no database" case and must produce exactly the
    static answer everywhere it is consulted.
    """

    server_version: int | None = None
    """The PostgreSQL **major** (``16``), or ``None`` when it was not read."""

    column_types: Mapping[str, str] = field(default_factory=dict)
    """``schema.table.column`` (case-folded) → the column's current type."""

    def column_type(self, qualified: str | None) -> str | None:
        """The current type of ``schema.table.column``, or ``None`` if unknown."""
        if not qualified:
            return None
        return self.column_types.get(qualified.lower())

    def __bool__(self) -> bool:
        """False when nothing was learned, so callers can skip the refined path."""
        return self.server_version is not None or bool(self.column_types)


def collect_schema_facts(conn: Any) -> SchemaFacts:
    """Read the facts above from an open connection. Never raises.

    ``conn`` is a psycopg connection, typed loosely so this module stays
    importable on the no-database path without dragging psycopg in with it.
    """
    return SchemaFacts(
        server_version=_server_version(conn),
        column_types=_column_types(conn),
    )


def _server_version(conn: Any) -> int | None:
    """The server *major* version.

    Prefers the connection's own attribute (no round trip); falls back to
    ``SHOW server_version_num``. psycopg reports ``160004`` for 16.4, and 90603
    for the 9.x scheme — both floor-divide to the major by the same rule only
    above 10, so the 9.x case is handled explicitly.
    """
    raw = getattr(getattr(conn, "info", None), "server_version", None)
    if raw is None:
        raw = _scalar(conn, "SHOW server_version_num")
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number // 10000 if number >= 100000 else number // 10000 or number // 100 % 100


def _column_types(conn: Any) -> dict[str, str]:
    try:
        with conn.cursor() as cur:
            cur.execute(_COLUMN_TYPE_SQL)
            rows = cur.fetchall()
    except Exception:  # noqa: BLE001 — refinement is optional; never fail preflight for it
        return {}
    types: dict[str, str] = {}
    for row in rows or ():
        try:
            schema, table, column, data_type = row[0], row[1], row[2], row[3]
        except (IndexError, TypeError):
            continue
        if schema and table and column and data_type:
            types[f"{schema}.{table}.{column}".lower()] = str(data_type)
    return types


def _scalar(conn: Any, sql: str) -> object | None:
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
    except Exception:  # noqa: BLE001 — see above
        return None
    return row[0] if row else None
