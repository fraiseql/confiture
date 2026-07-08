"""Query live view (and materialized-view) definitions from a database.

Enumerates ``pg_class`` relations of kind ``'v'`` (view) and ``'m'`` (materialized
view) in the requested schemas and returns each one's deparsed definition via
``pg_get_viewdef(oid, true)``. The same catalog is run against both the scratch
"expected" database and the live database so both sides pass through the identical
deparser — see :mod:`confiture.core.view_body_drift`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from confiture.core.view_body_drift import ViewDefinition

if TYPE_CHECKING:
    import psycopg

# One round-trip: enumerate views/matviews in the target schemas and deparse each.
_VIEW_DEFS_SQL = """\
SELECT n.nspname AS schema,
       c.relname AS name,
       c.relkind::text AS relkind,
       pg_get_viewdef(c.oid, true) AS definition
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('v', 'm')
  AND n.nspname = ANY(%(schemas)s)
ORDER BY n.nspname, c.relname
"""


class LiveViewCatalog:
    """Read view/matview definitions from an open connection.

    Args:
        connection: An open psycopg connection to the target database (live or
            the scratch expected DB).

    Example::

        catalog = LiveViewCatalog(conn)
        defs = catalog.get_view_definitions(["public", "catalog"])
        # {"public.v_orders": ViewDefinition(...), ...}
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._conn = connection

    def get_view_definitions(self, schemas: list[str] | None = None) -> dict[str, ViewDefinition]:
        """Return ``view_key`` → :class:`ViewDefinition` for the given schemas.

        Args:
            schemas: Schema names to enumerate (default: ``["public"]``).

        Returns:
            A dict keyed by ``"schema.name"``. Both regular views (``relkind
            'v'``) and materialized views (``relkind 'm'``) are included.
        """
        schemas = schemas or ["public"]
        result: dict[str, ViewDefinition] = {}
        for schema, name, relkind, definition in self._conn.execute(
            _VIEW_DEFS_SQL, {"schemas": schemas}
        ).fetchall():
            view = ViewDefinition(
                schema=schema,
                name=name,
                relkind=relkind,
                definition=definition,
            )
            result[view.view_key] = view
        return result
