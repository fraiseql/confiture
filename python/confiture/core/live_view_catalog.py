"""Query live view (and materialized-view) definitions from a database.

Every view (``'v'``) and materialized view (``'m'``) in the requested schemas,
with its deparsed definition — ``core/live_catalog``'s :func:`views`, which
deparses through ``pg_get_viewdef(oid, true)``. The same catalog is run against
both the scratch "expected" database and the live database so both sides pass
through the identical deparser — see :mod:`confiture.core.view_body_drift`.
An extension's own views are read too: both sides hold them, so they compare
equal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from confiture.core import live_catalog
from confiture.core.view_body_drift import ViewDefinition

if TYPE_CHECKING:
    import psycopg


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
        for row in live_catalog.views(self._conn, schemas, definitions=True):
            view = ViewDefinition(
                schema=row.schema,
                name=row.name,
                relkind=row.relkind,
                definition=row.definition or "",
            )
            result[view.view_key] = view
        return result
