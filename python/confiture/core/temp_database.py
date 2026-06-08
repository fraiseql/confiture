"""Temporary database lifecycle and pg_dump wrapper.

Creates throwaway PostgreSQL databases for live schema snapshots.
Used by ``SchemaSnapshotGenerator`` when ``--live-snapshot`` is active.
"""

from __future__ import annotations

import re
import subprocess
import uuid
from urllib.parse import urlparse, urlunparse

import psycopg
import psycopg.sql

from confiture.exceptions import SchemaError


def _maintenance_url(server_url: str) -> str:
    """Replace the database component of *server_url* with ``postgres``.

    The maintenance DB is used to issue ``CREATE DATABASE`` / ``DROP DATABASE``
    since the user's target database may not exist yet.
    """
    parsed = urlparse(server_url)
    return urlunparse(parsed._replace(path="/postgres"))


def _replace_dbname(server_url: str, dbname: str) -> str:
    """Return *server_url* with its database component replaced by *dbname*."""
    parsed = urlparse(server_url)
    return urlunparse(parsed._replace(path=f"/{dbname}"))


def terminate_backends(conn: psycopg.Connection, db_name: str) -> None:
    """Terminate all other sessions connected to *db_name*.

    Needed before ``CREATE DATABASE … WITH TEMPLATE`` (PostgreSQL forbids cloning
    a database that has other active sessions) and before dropping on PG < 13.

    Args:
        conn: An autocommit maintenance connection.
        db_name: Database whose backends should be terminated.
    """
    conn.execute(
        "SELECT pg_terminate_backend(pid) "
        "FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (db_name,),
    )


def force_drop_database(conn: psycopg.Connection, db_name: str) -> None:
    """Drop *db_name* if it exists, terminating any remaining backends first.

    Uses ``DROP DATABASE … WITH (FORCE)`` on PostgreSQL >= 13, falling back to an
    explicit :func:`terminate_backends` + plain ``DROP DATABASE`` on older
    versions. The database name is quoted via :class:`psycopg.sql.Identifier`
    (never string-interpolated).

    Args:
        conn: An autocommit maintenance connection.
        db_name: Database to drop.
    """
    db_id = psycopg.sql.Identifier(db_name)
    if conn.info.server_version >= 130000:
        conn.execute(psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(db_id))
    else:
        terminate_backends(conn, db_name)
        conn.execute(psycopg.sql.SQL("DROP DATABASE IF EXISTS {}").format(db_id))


class TempDatabase:
    """Context manager that creates a throwaway PostgreSQL database.

    On enter, creates a uniquely-named database and returns a connection URL.
    On exit, drops the database unconditionally (``WITH (FORCE)`` on PG >= 13,
    ``pg_terminate_backend`` fallback on older versions).

    The context manager connects to the ``postgres`` maintenance database —
    never to the user's target database, which may not exist.

    Args:
        server_url: PostgreSQL connection URL.  The database component is
            ignored; the maintenance DB (``postgres``) is used instead.

    Example::

        with TempDatabase("postgresql://localhost/myapp") as temp_url:
            with psycopg.connect(temp_url, autocommit=True) as conn:
                conn.execute(schema_sql, prepare=False)
    """

    def __init__(self, server_url: str) -> None:
        self._server_url = server_url
        self._db_name = f"confiture_tmp_{uuid.uuid4().hex[:8]}"
        self._maintenance_url = _maintenance_url(server_url)
        self._maintenance_conn: psycopg.Connection | None = None
        self._server_version: int = 0

    def __enter__(self) -> str:
        try:
            self._maintenance_conn = psycopg.connect(self._maintenance_url, autocommit=True)
        except psycopg.OperationalError as exc:
            raise SchemaError(
                f"Cannot connect to PostgreSQL server: {exc}",
                resolution_hint=(
                    "Ensure the PostgreSQL server is running and the connection URL is correct."
                ),
            ) from exc

        self._server_version = self._maintenance_conn.info.server_version

        self._maintenance_conn.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(self._db_name))
        )
        return _replace_dbname(self._server_url, self._db_name)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self._drop_database()

    def _drop_database(self) -> None:
        """Drop the temporary database, reconnecting if necessary."""
        try:
            conn = self._maintenance_conn
            if conn is None or conn.closed:
                conn = psycopg.connect(self._maintenance_url, autocommit=True)
                self._maintenance_conn = conn

            db_id = psycopg.sql.Identifier(self._db_name)

            if self._server_version >= 130000:
                conn.execute(
                    psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(db_id)
                )
            else:
                conn.execute(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (self._db_name,),
                )
                conn.execute(psycopg.sql.SQL("DROP DATABASE IF EXISTS {}").format(db_id))
        except Exception:
            pass  # best-effort cleanup
        finally:
            if self._maintenance_conn is not None and not self._maintenance_conn.closed:
                self._maintenance_conn.close()

    def apply_schema(self, temp_db_url: str, schema_sql: str) -> None:
        """Execute multi-statement schema SQL on the temporary database.

        Uses the simple query protocol (``prepare=False``) so that
        multi-statement strings and DO blocks work correctly.

        Args:
            temp_db_url: Connection URL for the temporary database
                (as returned by ``__enter__``).
            schema_sql: Full schema SQL to execute.

        Raises:
            SchemaError: If schema application fails.
        """
        try:
            with psycopg.connect(temp_db_url, autocommit=True) as conn:
                conn.execute(schema_sql, prepare=False)
        except psycopg.Error as exc:
            msg = f"Schema application failed in temporary database: {exc}"
            hint = "Check your DDL files for syntax errors."
            err_str = str(exc).lower()
            if "extension" in err_str and "does not exist" in err_str:
                hint = (
                    "A CREATE EXTENSION statement failed. Ensure the required "
                    "extension is installed on the PostgreSQL server "
                    "(e.g. apt install postgresql-XX-postgis)."
                )
            raise SchemaError(msg, resolution_hint=hint) from exc


def pg_dump_schema(database_url: str) -> str:
    """Run ``pg_dump --schema-only`` and return the DDL output.

    Args:
        database_url: PostgreSQL connection URL for the database to dump.

    Returns:
        Raw ``pg_dump`` output as a string.

    Raises:
        SchemaError: If ``pg_dump`` is not found, or the dump fails.
    """
    try:
        result = subprocess.run(
            ["pg_dump", "--schema-only", "--no-owner", "--no-privileges", database_url],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise SchemaError(
            "pg_dump not found on PATH. Install postgresql-client.",
            resolution_hint="Install postgresql-client (e.g. apt install postgresql-client).",
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        if "server version" in stderr and "pg_dump version" in stderr:
            raise SchemaError(
                "pg_dump is older than the PostgreSQL server. "
                "Upgrade postgresql-client to match your server version.",
                resolution_hint="Upgrade postgresql-client to match your server version.",
            ) from exc
        raise SchemaError(
            f"pg_dump failed: {stderr.strip()}",
            resolution_hint="Check the database URL and ensure the database exists.",
        ) from exc
    return result.stdout


_PG_DUMP_NOISE_RE = re.compile(
    r"^("
    r"SET\s|"
    r"SELECT\s+pg_catalog\.set_config|"
    r"--\s*Dumped\s+(from|by)\s|"
    r"CREATE\s+EXTENSION\s|"
    r"COMMENT\s+ON\s+EXTENSION\s"
    r")",
    re.IGNORECASE,
)


def clean_pg_dump_output(raw: str) -> str:
    """Strip ``pg_dump`` preamble noise from raw output.

    Removes ``SET`` session variables, ``SELECT pg_catalog.set_config``,
    ``CREATE EXTENSION``, ``COMMENT ON EXTENSION``, and
    ``-- Dumped from/by`` version comments.
    """
    lines = raw.splitlines(keepends=True)
    return "".join(line for line in lines if not _PG_DUMP_NOISE_RE.match(line))
