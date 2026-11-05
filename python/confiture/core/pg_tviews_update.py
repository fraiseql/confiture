"""Bring a database's pg_tviews catalog to the library its server loaded (#809).

From pg_tviews 0.1.0-beta.35 an upgrade is a package install, a restart, and
``ALTER EXTENSION pg_tviews UPDATE`` in each database. Between the restart and the
update the library finds a catalog of another revision and refuses every write to a
TVIEW's base tables and every pg_tviews function (``55000``), so a migration that
writes would fail. ``migrate up`` runs the update first, under the migration lock,
when the loaded library is the package's release and the package's scripts lead to
it from the catalog: the update re-derives every TVIEW itself.

A release updates only from the one before it. A catalog with no update to the
library is refused (``CONFIG_016``) unless the operator asks for the recreate
(``--recreate-pg-tviews``): in one transaction, the extension is dropped with
pg_tviews' own objects, each TVIEW's table is dropped, the extension is created
again and every TVIEW the schema files declare is created from them, in the order
the build creates them, with its indexes. Nothing is dropped without that request,
nothing outside pg_tviews is dropped with it — a view that reads a TVIEW or
pg_tviews' schema refuses the recreate, naming it — and a failure leaves the
database as it was.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from string.templatelib import Template
from typing import Literal

import psycopg

from confiture.core import live_catalog
from confiture.core.ddl_objects import tview_object
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.schema_change import ObjectAdded
from confiture.core.schema_model import (
    TVIEWS_SCHEMA,
    RelationName,
    SchemaModel,
    TView,
    tview_ref,
)
from confiture.exceptions import ConfigurationError

#: What :func:`bring_up_to_date` did.
Action = Literal["updated", "recreated"]


@dataclass(frozen=True)
class CatalogUpdate:
    """The catalog brought to the library: from which release, to which, and how.

    ``tviews`` are the TVIEWs a recreate created again, in the order it created them.
    """

    action: Action
    catalog: str
    library: str
    tviews: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        if self.action == "updated":
            return f"pg_tviews {self.catalog} updated to {self.library}"
        return (
            f"pg_tviews {self.catalog} dropped and created again at {self.library}, "
            f"with {len(self.tviews)} TVIEW(s) created from the schema files"
        )


def needs_update(conn: psycopg.Connection) -> live_catalog.PgTviewsReleases | None:
    """The releases *conn*'s database runs when its catalog is not the loaded library's.

    ``None`` without the extension, or when the catalog is the library's already.
    """
    releases = live_catalog.pg_tviews_releases(conn)
    if releases is None or _library(releases) == releases.catalog:
        return None
    return releases


def require_current(conn: psycopg.Connection) -> None:
    """Refuse a database whose catalog is not the loaded library's, changing nothing.

    What a dry run asks: it updates nothing, and in that window pg_tviews refuses
    every DDL statement, confiture's own bookkeeping included.

    Raises:
        ConfigurationError: ``CONFIG_016``, naming the update a real run makes first.
    """
    releases = needs_update(conn)
    if releases is not None:
        raise _refused(
            releases,
            "pg_tviews refuses every write and DDL statement until the catalog is updated, "
            "and a dry run changes nothing",
            "Run confiture migrate up without --dry-run: it updates the catalog first "
            "(ALTER EXTENSION pg_tviews UPDATE), or run that statement yourself",
        )


def bring_up_to_date(
    conn: psycopg.Connection, *, recreate_from: SchemaModel | None = None
) -> CatalogUpdate | None:
    """Update *conn*'s pg_tviews catalog to the loaded library; ``None`` when it already is.

    *recreate_from* is the schema the TVIEWs are created again from when the
    catalog has no update to the library; ``None`` refuses that case. The work is
    committed before this returns, or rolled back when it fails.

    Raises:
        ConfigurationError: ``CONFIG_016`` when the catalog cannot be brought to the
            library — the loaded library is not the installed package (PostgreSQL
            was not restarted), the catalog has no update and no recreate was asked
            for, the recreate would take a view along or cannot create a TVIEW the
            database registers, or PostgreSQL refused a statement.
    """
    releases = needs_update(conn)
    if releases is None:
        return None
    library = _library(releases)
    if library is None or (releases.package is not None and library != releases.package):
        raise _refused(
            releases,
            f"the loaded library is not the installed package ({releases.package}); "
            "PostgreSQL was not restarted since the package was installed",
            "Restart PostgreSQL so it loads the installed pg_tviews, then run confiture again",
        )
    if releases.update_path:
        _in_one_transaction(conn, [t"ALTER EXTENSION pg_tviews UPDATE TO {library:l}"], releases)
        return CatalogUpdate("updated", releases.catalog, library)
    if recreate_from is None:
        raise _refused(
            releases,
            f"pg_tviews {library} has no update from {releases.catalog}",
            "Drop the extension and create every TVIEW again from the schema files: "
            "confiture migrate up --recreate-pg-tviews (one transaction; base tables "
            "keep their rows, TVIEWs are refilled from them)",
        )
    return _recreate(conn, releases, library, recreate_from)


def _library(releases: live_catalog.PgTviewsReleases) -> str | None:
    """The loaded library's release: a catalog too old to say is taken at the package's."""
    return releases.library or releases.package


def _recreate(
    conn: psycopg.Connection,
    releases: live_catalog.PgTviewsReleases,
    library: str,
    tree: SchemaModel,
) -> CatalogUpdate:
    registered = _registered(conn)
    declared = list(tree.tviews.values())
    identities = {_relation(tview).identity for tview in declared}
    undeclared = [r for r in registered if r.identity not in identities]
    if undeclared:
        raise _refused(
            releases,
            "the database registers TVIEWs the schema files do not declare: "
            + ", ".join(r.qualified for r in undeclared),
            "Declare them in the schema files, or drop them, before the recreate",
        )
    tables = {r.identity: r for r in [*registered, *map(_relation, declared)]}
    readers = live_catalog.readers_of_pg_tviews(conn, list(tables.values()))
    if readers:
        raise _refused(
            releases,
            "dropping pg_tviews would drop the views that read it: "
            + ", ".join(r.qualified for r in readers),
            "Drop those views, recreate pg_tviews, and create them again",
        )
    statements: list[str | Template] = [
        "DROP EXTENSION pg_tviews CASCADE",
        t"DROP SCHEMA IF EXISTS {TVIEWS_SCHEMA:i} CASCADE",
        *(t"DROP TABLE IF EXISTS {schema:i}.{name:i}" for schema, name in tables),
        "CREATE EXTENSION pg_tviews CASCADE",
    ]
    generator = DifferSQLGenerator()
    for tview in declared:
        ref = tview_ref(tview)
        created = generator.generate_up(
            ObjectAdded(ref, tview_object(ref, tview), tview.indexes or ())
        )
        if created:
            statements.append(created)
    _in_one_transaction(conn, statements, releases)
    return CatalogUpdate(
        "recreated", releases.catalog, library, tuple(t.qualified for t in declared)
    )


def _registered(conn: psycopg.Connection) -> list[RelationName]:
    """The TVIEWs the catalog registers; none when it has no ``tviews.registry``.

    The registry is plain SQL over pg_tviews' tables: it reads while the library
    refuses the catalog.
    """
    if not live_catalog.relation_exists(conn, TVIEWS_SCHEMA, "registry", ("v", "r")):
        return []
    with conn.cursor() as cursor:
        cursor.execute(t"SELECT schema, name FROM {TVIEWS_SCHEMA:i}.registry ORDER BY 1, 2")
        return [RelationName(schema, name) for schema, name in cursor.fetchall()]


def _relation(tview: TView) -> RelationName:
    return RelationName(tview.schema, tview.name)


def _in_one_transaction(
    conn: psycopg.Connection,
    statements: Sequence[str | Template],
    releases: live_catalog.PgTviewsReleases,
) -> None:
    """Run *statements* and commit, or roll back and refuse naming PostgreSQL's error."""
    try:
        with conn.transaction(), conn.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        if not conn.autocommit:
            conn.commit()
    except psycopg.Error as error:
        if not conn.autocommit:
            conn.rollback()
        raise _refused(
            releases,
            f"PostgreSQL refused it: {error}".rstrip(),
            "ALTER EXTENSION and DROP/CREATE EXTENSION need the extension's owner or a "
            "superuser, and jsonb_delta installed (pg_tviews requires it); nothing was changed",
        ) from error


def _refused(releases: live_catalog.PgTviewsReleases, why: str, hint: str) -> ConfigurationError:
    library = _library(releases) or "of an unknown release"
    return ConfigurationError(
        f"pg_tviews {releases.catalog} in this database cannot be brought to the loaded "
        f"library {library}: {why}",
        error_code="CONFIG_016",
        resolution_hint=hint,
    )
