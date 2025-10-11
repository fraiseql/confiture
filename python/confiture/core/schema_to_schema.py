"""Schema-to-Schema Migration using Foreign Data Wrapper (FDW).

This module implements Medium 4: Schema-to-Schema migration for zero-downtime
database migrations. It supports two strategies:

1. FDW Strategy: Best for small-medium tables (<10M rows), complex transformations
2. COPY Strategy: Best for large tables (>10M rows), 10-20x faster (Milestone 3.3)

Phase 3, Milestone 3.1: FDW Strategy Setup
"""

from typing import Any

import psycopg
from psycopg import sql

from confiture.exceptions import MigrationError

# Constants for FDW configuration
DEFAULT_FOREIGN_SCHEMA_NAME = "old_schema"
DEFAULT_SERVER_NAME = "confiture_source_server"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = "5432"


class SchemaToSchemaMigrator:
    """Migrator for schema-to-schema migrations using FDW.

    This class manages the migration of data from an old database schema to a
    new database schema using PostgreSQL Foreign Data Wrapper (FDW).

    Attributes:
        source_connection: Connection to source (old) database
        target_connection: Connection to target (new) database
        foreign_schema_name: Name for the imported foreign schema
    """

    def __init__(
        self,
        source_connection: psycopg.Connection,
        target_connection: psycopg.Connection,
        foreign_schema_name: str = DEFAULT_FOREIGN_SCHEMA_NAME,
        server_name: str = DEFAULT_SERVER_NAME,
    ):
        """Initialize schema-to-schema migrator.

        Args:
            source_connection: PostgreSQL connection to source database
            target_connection: PostgreSQL connection to target database
            foreign_schema_name: Name for imported foreign schema
            server_name: Name for the foreign server
        """
        self.source_connection = source_connection
        self.target_connection = target_connection
        self.foreign_schema_name = foreign_schema_name
        self.server_name = server_name

    def _get_connection_params(self) -> tuple[str, str]:
        """Extract database connection parameters from source connection.

        Returns:
            Tuple of (dbname, user)
        """
        source_info = self.source_connection.info
        source_params = source_info.get_parameters()
        dbname = source_params.get("dbname", "postgres")
        user = source_params.get("user", "postgres")
        return dbname, user

    def _create_fdw_extension(self, cursor: psycopg.Cursor) -> None:
        """Create postgres_fdw extension if not exists.

        Args:
            cursor: Database cursor
        """
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgres_fdw")

    def _create_foreign_server(self, cursor: psycopg.Cursor, dbname: str) -> None:
        """Create foreign server pointing to source database.

        Args:
            cursor: Database cursor
            dbname: Source database name
        """
        cursor.execute(
            sql.SQL("""
                CREATE SERVER IF NOT EXISTS {server}
                FOREIGN DATA WRAPPER postgres_fdw
                OPTIONS (
                    host {host},
                    dbname {dbname},
                    port {port}
                )
            """).format(
                server=sql.Identifier(self.server_name),
                host=sql.Literal(DEFAULT_HOST),
                dbname=sql.Literal(dbname),
                port=sql.Literal(DEFAULT_PORT),
            )
        )

    def _create_user_mapping(self, cursor: psycopg.Cursor, user: str) -> None:
        """Create user mapping for foreign server authentication.

        Args:
            cursor: Database cursor
            user: Source database user
        """
        cursor.execute(
            sql.SQL("""
                CREATE USER MAPPING IF NOT EXISTS FOR CURRENT_USER
                SERVER {server}
                OPTIONS (
                    user {user},
                    password ''
                )
            """).format(server=sql.Identifier(self.server_name), user=sql.Literal(user))
        )

    def _create_foreign_schema(self, cursor: psycopg.Cursor) -> None:
        """Create foreign schema container.

        Args:
            cursor: Database cursor
        """
        cursor.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {schema}").format(
                schema=sql.Identifier(self.foreign_schema_name)
            )
        )

    def _import_foreign_schema(self, cursor: psycopg.Cursor) -> None:
        """Import foreign schema tables from source database.

        Args:
            cursor: Database cursor
        """
        cursor.execute(
            sql.SQL("""
                IMPORT FOREIGN SCHEMA public
                FROM SERVER {server}
                INTO {schema}
            """).format(
                server=sql.Identifier(self.server_name),
                schema=sql.Identifier(self.foreign_schema_name),
            )
        )

    def setup_fdw(self, skip_import: bool = False) -> None:
        """Setup Foreign Data Wrapper to source database.

        This method performs the following steps:
        1. Creates postgres_fdw extension if not exists
        2. Creates foreign server pointing to source database
        3. Creates user mapping for authentication
        4. Creates foreign schema
        5. Optionally imports foreign schema from source database

        Args:
            skip_import: If True, skip importing foreign schema (useful for testing)

        Raises:
            MigrationError: If FDW setup fails
        """
        try:
            with self.target_connection.cursor() as cursor:
                # Get connection parameters
                dbname, user = self._get_connection_params()

                # Setup FDW infrastructure
                self._create_fdw_extension(cursor)
                self._create_foreign_server(cursor, dbname)
                self._create_user_mapping(cursor, user)
                self._create_foreign_schema(cursor)

                # Import schema if requested
                if not skip_import:
                    self._import_foreign_schema(cursor)

            self.target_connection.commit()

        except psycopg.Error as e:
            self.target_connection.rollback()
            raise MigrationError(f"Failed to setup FDW: {e}") from e

    def cleanup_fdw(self) -> None:
        """Clean up FDW resources (server, mappings, schema).

        This method removes all FDW-related resources created by setup_fdw().
        Useful for testing or manual cleanup.

        Raises:
            MigrationError: If cleanup fails
        """
        try:
            with self.target_connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {schema} CASCADE").format(
                        schema=sql.Identifier(self.foreign_schema_name)
                    )
                )
                cursor.execute(
                    sql.SQL(
                        "DROP USER MAPPING IF EXISTS FOR CURRENT_USER SERVER {server}"
                    ).format(server=sql.Identifier(self.server_name))
                )
                cursor.execute(
                    sql.SQL("DROP SERVER IF EXISTS {server} CASCADE").format(
                        server=sql.Identifier(self.server_name)
                    )
                )

            self.target_connection.commit()

        except psycopg.Error as e:
            self.target_connection.rollback()
            raise MigrationError(f"Failed to cleanup FDW: {e}") from e

    def migrate_table(
        self,
        table_name: str,
        column_mapping: dict[str, str] | None = None,
    ) -> None:
        """Migrate data from source table to target table with column mapping.

        This method will be implemented in Milestone 3.2.

        Args:
            table_name: Name of table to migrate
            column_mapping: Mapping of old column names to new column names

        Raises:
            NotImplementedError: Not yet implemented (Milestone 3.2)
        """
        raise NotImplementedError("migrate_table will be implemented in Milestone 3.2")

    def analyze_tables(self) -> dict[str, dict[str, Any]]:
        """Analyze table sizes and recommend optimal migration strategy.

        This method will be implemented in Milestone 3.4 (Hybrid Strategy).

        Returns:
            Dictionary mapping table names to strategy recommendations

        Raises:
            NotImplementedError: Not yet implemented (Milestone 3.4)
        """
        raise NotImplementedError("analyze_tables will be implemented in Milestone 3.4")
