"""View dependency manager for ALTER COLUMN TYPE migrations.

PostgreSQL prevents ALTER COLUMN TYPE when views depend on the column.
This module provides automated view lifecycle management:

1. Discover all dependent views (including transitive: views-on-views)
2. Save their definitions, indexes, and comments
3. Drop them in reverse dependency order
4. (User runs ALTER statements)
5. Recreate views in forward dependency order
6. Restore indexes and comments

Usage in a Python migration::

    from confiture.core.view_manager import ViewManager

    class UpgradePkToBigint(Migration):
        version = "003"
        name = "upgrade_pk_to_bigint"

        def up(self):
            vm = ViewManager(self.connection)
            vm.save_and_drop_dependent_views(schemas=["public", "catalog"])

            self.execute("ALTER TABLE tb_machine ALTER COLUMN pk_machine TYPE BIGINT")

            vm.recreate_saved_views()
"""

import logging
from dataclasses import dataclass, field
from importlib import resources

import psycopg

logger = logging.getLogger(__name__)

# SQL: Recursive CTE to discover all views depending on tables in given schemas.
# Handles regular views (relkind='v') and materialized views (relkind='m').
# Includes partitioned tables (relkind='p') alongside regular tables (relkind='r').
_DISCOVER_VIEWS_SQL = """\
WITH RECURSIVE
-- Step 1: Find all base tables in the target schemas
base_tables AS (
    SELECT c.oid
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = ANY(%(schemas)s)
      AND c.relkind IN ('r', 'p')
),
-- Step 2: Recursively find dependent views
view_deps AS (
    -- Direct dependents of base tables
    SELECT DISTINCT
        dep_view.oid,
        dep_ns.nspname  AS schema,
        dep_view.relname AS name,
        dep_view.relkind::text AS kind,
        0 AS depth
    FROM pg_depend d
    JOIN pg_rewrite rw ON d.objid = rw.oid
    JOIN pg_class dep_view ON rw.ev_class = dep_view.oid
    JOIN pg_namespace dep_ns ON dep_view.relnamespace = dep_ns.oid
    WHERE d.refobjid IN (SELECT oid FROM base_tables)
      AND dep_view.relkind IN ('v', 'm')
      AND d.deptype = 'n'
      AND dep_view.oid != d.refobjid

    UNION

    -- Transitive dependents (views on views)
    SELECT DISTINCT
        dep_view.oid,
        dep_ns.nspname,
        dep_view.relname,
        dep_view.relkind::text,
        vd.depth + 1
    FROM view_deps vd
    JOIN pg_depend d ON d.refobjid = vd.oid
    JOIN pg_rewrite rw ON d.objid = rw.oid
    JOIN pg_class dep_view ON rw.ev_class = dep_view.oid
    JOIN pg_namespace dep_ns ON dep_view.relnamespace = dep_ns.oid
    WHERE dep_view.relkind IN ('v', 'm')
      AND dep_view.oid != vd.oid
      AND d.deptype = 'n'
)
SELECT DISTINCT ON (oid) oid, schema, name, kind, depth
FROM view_deps
ORDER BY oid, depth DESC
"""

# SQL: Get the definition of a view
_VIEW_DEF_SQL = "SELECT pg_get_viewdef(%(oid)s, true)"

# SQL: Get indexes on a materialized view
_MATVIEW_INDEXES_SQL = """\
SELECT indexname, pg_get_indexdef(i.indexrelid)
FROM pg_indexes pi
JOIN pg_index i ON i.indexrelid = (
    SELECT c.oid FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = pi.schemaname AND c.relname = pi.indexname
)
WHERE pi.schemaname = %(schema)s AND pi.tablename = %(name)s
"""

# SQL: Get comment on a view/materialized view
_VIEW_COMMENT_SQL = """\
SELECT obj_description(c.oid)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %(schema)s AND c.relname = %(name)s
"""


@dataclass
class SavedViewIndex:
    """A saved index definition for a materialized view."""

    name: str
    definition: str  # Full CREATE INDEX DDL


@dataclass
class SavedView:
    """A saved view definition with metadata for recreation."""

    oid: int
    schema: str
    name: str
    kind: str  # 'v' = regular view, 'm' = materialized view
    depth: int
    definition: str  # View body (from pg_get_viewdef)
    indexes: list[SavedViewIndex] = field(default_factory=list)
    comment: str | None = None


class ViewManager:
    """Manages view lifecycle during ALTER COLUMN TYPE migrations.

    Provides methods to discover, save, drop, and recreate views that
    depend on tables in specified schemas. This is the core Python API;
    equivalent SQL helper functions are available for use in .up.sql
    migrations.

    Args:
        connection: An open psycopg connection to the target database.

    Example::

        vm = ViewManager(connection)
        vm.save_and_drop_dependent_views(schemas=["public"])
        # ... ALTER COLUMN TYPE statements ...
        vm.recreate_saved_views()
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._conn = connection
        self._saved_views: list[SavedView] = []

    def install_helpers(self) -> None:
        """Install SQL helper functions in the target database.

        Creates the ``confiture`` schema and installs
        ``confiture.save_and_drop_dependent_views()`` and
        ``confiture.recreate_saved_views()`` PL/pgSQL functions.

        This is idempotent — safe to call multiple times (uses
        ``CREATE SCHEMA IF NOT EXISTS`` and ``CREATE OR REPLACE FUNCTION``).

        Raises:
            psycopg.Error: If the SQL cannot be executed.
        """
        sql = resources.files("confiture.sql").joinpath("view_helpers.sql").read_text()
        with self._conn.cursor() as cur:
            cur.execute(sql)
        self._conn.commit()
        logger.info("Installed confiture view helper functions")

    def helpers_installed(self) -> bool:
        """Check whether the SQL helper functions are installed.

        Returns:
            True if the ``confiture`` schema and both helper functions exist.
        """
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'confiture'
                  AND p.proname IN ('save_and_drop_dependent_views', 'recreate_saved_views')
            """)
            row = cur.fetchone()
            return bool(row and row[0] >= 2)

    def discover_dependent_views(self, schemas: list[str] | None = None) -> list[SavedView]:
        """Discover all views that depend on tables in the given schemas.

        Uses a recursive CTE over pg_depend/pg_rewrite to find both direct
        and transitive view dependencies. Includes regular views and
        materialized views.

        Args:
            schemas: List of PostgreSQL schema names to scan for base tables.
                If None, scans all user schemas (excludes pg_* and
                information_schema).

        Returns:
            List of SavedView objects sorted by depth descending (deepest first),
            suitable for drop order. Each SavedView includes the view definition,
            indexes (for materialized views), and comments.
        """
        if schemas is None:
            schemas = self._get_user_schemas()

        with self._conn.cursor() as cur:
            cur.execute(_DISCOVER_VIEWS_SQL, {"schemas": schemas})
            rows = cur.fetchall()

        views: list[SavedView] = []
        for oid, schema, name, kind, depth in rows:
            view = SavedView(
                oid=oid,
                schema=schema,
                name=name,
                kind=kind,
                depth=depth,
                definition="",
            )
            # Fetch view definition
            view.definition = self._get_view_definition(oid)
            # Fetch indexes for materialized views
            if kind == "m":
                view.indexes = self._get_matview_indexes(schema, name)
            # Fetch comment
            view.comment = self._get_view_comment(schema, name)
            views.append(view)

        # Sort by depth descending (deepest first = drop order)
        views.sort(key=lambda v: (-v.depth, v.schema, v.name))
        return views

    def save_and_drop_dependent_views(self, schemas: list[str] | None = None) -> int:
        """Save definitions of all dependent views, then drop them.

        Views are dropped in reverse dependency order (deepest first) to
        avoid PostgreSQL dependency errors. Saved definitions are stored
        in memory for later recreation via ``recreate_saved_views()``.

        Args:
            schemas: List of PostgreSQL schema names to scan for base tables.
                If None, scans all user schemas.

        Returns:
            Number of views dropped.

        Raises:
            psycopg.Error: If a view cannot be dropped.
        """
        self._saved_views = self.discover_dependent_views(schemas)

        if not self._saved_views:
            logger.info("No dependent views found — nothing to drop")
            return 0

        logger.info(
            "Saving and dropping %d dependent view(s): %s",
            len(self._saved_views),
            ", ".join(f"{v.schema}.{v.name}" for v in self._saved_views),
        )

        # Drop in reverse dependency order (deepest first — already sorted)
        with self._conn.cursor() as cur:
            for view in self._saved_views:
                qualified = f'"{view.schema}"."{view.name}"'
                if view.kind == "m":
                    cur.execute(f"DROP MATERIALIZED VIEW IF EXISTS {qualified} CASCADE")
                else:
                    cur.execute(f"DROP VIEW IF EXISTS {qualified} CASCADE")
                logger.debug(
                    "Dropped %s %s", "MATERIALIZED VIEW" if view.kind == "m" else "VIEW", qualified
                )

        self._conn.commit()
        return len(self._saved_views)

    def recreate_saved_views(self) -> int:
        """Recreate all previously saved views in forward dependency order.

        Views are recreated shallowest-first so that views depending on
        other views are created after their dependencies. Materialized
        views are created with ``WITH NO DATA`` then refreshed. Indexes
        and comments are restored.

        Returns:
            Number of views recreated.

        Raises:
            RuntimeError: If no views have been saved (call save_and_drop first).
            psycopg.Error: If a view cannot be recreated.
        """
        if not self._saved_views:
            logger.info("No saved views to recreate")
            return 0

        # Recreate in forward order (shallowest first)
        ordered = sorted(self._saved_views, key=lambda v: (v.depth, v.schema, v.name))

        logger.info(
            "Recreating %d view(s): %s",
            len(ordered),
            ", ".join(f"{v.schema}.{v.name}" for v in ordered),
        )

        with self._conn.cursor() as cur:
            for view in ordered:
                qualified = f'"{view.schema}"."{view.name}"'
                definition = view.definition.rstrip().rstrip(";")

                if view.kind == "m":
                    cur.execute(
                        f"CREATE MATERIALIZED VIEW {qualified} AS {definition} WITH NO DATA"
                    )
                    cur.execute(f"REFRESH MATERIALIZED VIEW {qualified}")
                    logger.debug("Recreated MATERIALIZED VIEW %s", qualified)
                else:
                    cur.execute(f"CREATE VIEW {qualified} AS {definition}")
                    logger.debug("Recreated VIEW %s", qualified)

                # Restore indexes (materialized views only)
                for idx in view.indexes:
                    cur.execute(idx.definition)
                    logger.debug("Recreated index %s", idx.name)

                # Restore comment
                if view.comment:
                    kind_label = "MATERIALIZED VIEW" if view.kind == "m" else "VIEW"
                    # COMMENT ON is DDL and doesn't support parameterized queries,
                    # so we must use a literal. Escape single quotes for safety.
                    escaped = view.comment.replace("'", "''")
                    cur.execute(f"COMMENT ON {kind_label} {qualified} IS '{escaped}'")

        self._conn.commit()

        count = len(self._saved_views)
        self._saved_views = []
        return count

    def get_saved_views(self) -> list[SavedView]:
        """Return the currently saved views (for inspection/debugging).

        Returns:
            List of SavedView objects currently held in memory.
        """
        return list(self._saved_views)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_user_schemas(self) -> list[str]:
        """Return all user-defined schemas (excludes system schemas)."""
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT nspname FROM pg_namespace
                WHERE nspname NOT LIKE 'pg_%%'
                  AND nspname != 'information_schema'
                ORDER BY nspname
            """)
            return [row[0] for row in cur.fetchall()]

    def _get_view_definition(self, oid: int) -> str:
        """Get the SQL body of a view from pg_get_viewdef."""
        with self._conn.cursor() as cur:
            cur.execute(_VIEW_DEF_SQL, {"oid": oid})
            row = cur.fetchone()
            return str(row[0]) if row else ""

    def _get_matview_indexes(self, schema: str, name: str) -> list[SavedViewIndex]:
        """Get all index definitions for a materialized view."""
        with self._conn.cursor() as cur:
            cur.execute(_MATVIEW_INDEXES_SQL, {"schema": schema, "name": name})
            return [SavedViewIndex(name=row[0], definition=row[1]) for row in cur.fetchall()]

    def _get_view_comment(self, schema: str, name: str) -> str | None:
        """Get the comment on a view, or None if no comment."""
        with self._conn.cursor() as cur:
            cur.execute(_VIEW_COMMENT_SQL, {"schema": schema, "name": name})
            row = cur.fetchone()
            return row[0] if row and row[0] else None
