"""Build an "expected" schema into a throwaway database for pg-normalised readback.

The recurring need across the drift-guard features (view drift #174, replay drift
#179, require-migration bodies #178) is: materialise the schema the repository
*expects* into a scratch database, then read it back through PostgreSQL's own
catalogs and deparser (``pg_get_viewdef``, ``pg_proc.prosrc``). Reading both the
expected and the live side through the identical deparser makes string equality
mean semantic equality — far more robust than text-normalising source DDL.

This module packages that pattern once, as a context manager that yields a live
connection to the scratch database, so each downstream feature runs its own
readback query instead of re-implementing the scratch-DB lifecycle.

Two build modes:

* :meth:`ExpectedSchemaDB.from_source` — apply the expected DDL (built from the
  ``db/schema`` files, or passed explicitly). This is the "build-from-DDL"
  expectation used by view drift (#174).
* :meth:`ExpectedSchemaDB.from_base_plus_migrations` — apply an optional base
  schema, then replay every migration in ``migrations_dir`` via ``migrate up``.
  This is the "migrate-strategy" expectation used by replay drift (#179) and
  require-migration bodies (#178).

The scratch database is always built on a **writable** maintenance server (given
by ``server_url``) — usually local or CI, and *not necessarily* the production
server whose live schema is being compared. The live (possibly remote,
read-only) connection is the caller's concern and stays entirely separate.

Usage::

    with ExpectedSchemaDB(server_url, env="production").from_source() as conn:
        viewdef = conn.execute(
            "SELECT pg_get_viewdef('public.my_view'::regclass, true)"
        ).fetchone()[0]
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg

from confiture.core.temp_database import TempDatabase
from confiture.exceptions import ConfigurationError, SchemaError

if TYPE_CHECKING:
    from types import TracebackType

    from confiture.config.environment import Environment

_MODE_SOURCE = "source"
_MODE_MIGRATIONS = "migrations"


class ExpectedSchemaDB:
    """Context manager that builds the expected schema into a throwaway database.

    Select a build mode with :meth:`from_source` or
    :meth:`from_base_plus_migrations` (both return ``self`` for chaining), then
    enter the context to receive a live :class:`psycopg.Connection` to the
    scratch database. On exit the scratch database is dropped unconditionally
    (delegated to :class:`~confiture.core.temp_database.TempDatabase`), even if
    the build raised.

    Args:
        server_url: Writable PostgreSQL server URL. Its database component is
            ignored — the scratch DB is created via the ``postgres`` maintenance
            database (see :class:`TempDatabase`).
        env: Environment name (or :class:`Environment`) used by
            :class:`~confiture.core.builder.SchemaBuilder` when building the
            expected DDL from ``db/schema`` files. Required for
            :meth:`from_source` unless explicit ``schema_sql`` is supplied.
        project_dir: Project root for :class:`SchemaBuilder` (defaults to cwd).
        migrations_dir: Directory of migration files for the replay mode
            (defaults to ``db/migrations``).
        migration_table: Optional tracking-table override for the replay.
    """

    def __init__(
        self,
        server_url: str,
        *,
        env: str | Environment | None = None,
        project_dir: Path | None = None,
        migrations_dir: Path | None = None,
        migration_table: str | None = None,
    ) -> None:
        self._server_url = server_url
        self._env = env
        self._project_dir = project_dir
        self._migrations_dir = migrations_dir or Path("db") / "migrations"
        self._migration_table = migration_table

        self._mode: str | None = None
        self._schema_sql: str | None = None
        self._base_sql: str | None = None

        self._stack: contextlib.ExitStack | None = None
        self._td: TempDatabase | None = None
        self._temp_url: str | None = None
        self._conn: psycopg.Connection | None = None

    # -- mode selection -------------------------------------------------- #

    def from_source(self, *, schema_sql: str | None = None) -> ExpectedSchemaDB:
        """Build the scratch DB from the expected DDL.

        Args:
            schema_sql: Explicit DDL to apply. When ``None``, the schema is built
                from the configured ``env`` via :class:`SchemaBuilder`
                (``schema_only=True``).
        """
        self._mode = _MODE_SOURCE
        self._schema_sql = schema_sql
        return self

    def from_base_plus_migrations(self, *, base_sql: str | None = None) -> ExpectedSchemaDB:
        """Build the scratch DB by replaying migrations.

        Applies ``base_sql`` first (if given), then runs ``migrate up`` over
        every migration in ``migrations_dir`` against the scratch DB. With
        ``base_sql=None`` the scratch starts empty and the migrations build the
        whole schema — the pure migrate-strategy expectation.

        Args:
            base_sql: Optional baseline DDL applied before the migration replay.
        """
        self._mode = _MODE_MIGRATIONS
        self._base_sql = base_sql
        return self

    # -- context management ---------------------------------------------- #

    def __enter__(self) -> psycopg.Connection:
        if self._mode is None:
            raise ConfigurationError(
                "ExpectedSchemaDB: choose a build mode before entering the context.",
                resolution_hint="Call .from_source() or .from_base_plus_migrations() first.",
            )

        self._stack = contextlib.ExitStack()
        try:
            # TempDatabase drops the scratch DB (WITH FORCE) when the stack closes.
            self._td = TempDatabase(self._server_url)
            self._temp_url = self._stack.enter_context(self._td)
            self._build()
            # Registered after TempDatabase → closed first on unwind (LIFO), so the
            # connection is gone before the DROP DATABASE runs.
            self._conn = self._stack.enter_context(psycopg.connect(self._temp_url, autocommit=True))
        except BaseException:
            # Any build/connect failure still tears down the scratch DB.
            self._stack.close()
            self._stack = None
            self._td = None
            raise
        return self._conn

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._stack is not None:
            self._stack.close()
            self._stack = None
        self._td = None
        self._conn = None
        self._temp_url = None

    # -- build strategies ------------------------------------------------ #

    def _build(self) -> None:
        assert self._td is not None and self._temp_url is not None  # set by __enter__
        if self._mode == _MODE_SOURCE:
            schema_sql = self._resolve_source_sql()
            self._td.apply_schema(self._temp_url, schema_sql)
        else:
            if self._base_sql:
                self._td.apply_schema(self._temp_url, self._base_sql)
            self._replay_migrations()

    def _resolve_source_sql(self) -> str:
        if self._schema_sql is not None:
            return self._schema_sql
        if self._env is None:
            raise ConfigurationError(
                "ExpectedSchemaDB.from_source needs an env or explicit schema_sql.",
                resolution_hint="Pass env= to the constructor or schema_sql= to from_source().",
            )
        from confiture.core.builder import SchemaBuilder

        return SchemaBuilder(env=self._env, project_dir=self._project_dir).build(schema_only=True)

    def _replay_migrations(self) -> None:
        from confiture.core._migrator.session import MigratorSession

        session = MigratorSession(
            config=None,
            migrations_dir=self._migrations_dir,
            database_url_override=self._temp_url,
            migration_table_override=self._migration_table,
        )
        with session:
            result = session.up()
        if not result.success:
            raise SchemaError(
                f"Migration replay into the scratch database failed: {result.errors}",
                resolution_hint="Fix the failing migration, then retry the drift check.",
            )
