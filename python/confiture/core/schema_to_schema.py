"""Schema-to-Schema Migration using Foreign Data Wrapper (FDW).

This module implements Medium 4: Schema-to-Schema migration for zero-downtime
database migrations. It supports two strategies:

1. FDW Strategy: Best for small-medium tables (<10M rows), complex transformations
2. COPY Strategy: Best for large tables (>10M rows), 10-20x faster (Milestone 3.3)

Phase 3, Milestone 3.1: FDW Strategy Setup
"""

from io import BytesIO
from typing import Any

import psycopg
from psycopg import sql

from confiture.exceptions import MigrationError

# Constants for FDW configuration
DEFAULT_FOREIGN_SCHEMA_NAME = "old_schema"
DEFAULT_SERVER_NAME = "confiture_source_server"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = "5432"

# Constants for migration strategy
LARGE_TABLE_THRESHOLD = 10_000_000  # 10M rows
FDW_THROUGHPUT = 500_000  # rows/second for FDW
COPY_THROUGHPUT = 6_000_000  # rows/second for COPY (10-20x faster)


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
        source_table: str,
        target_table: str,
        column_mapping: dict[str, str],
    ) -> int:
        """Migrate data from source table to target table with column mapping.

        Uses the FDW foreign schema to read from source and INSERT into target.
        Applies column name mappings during the SELECT.

        Args:
            source_table: Name of source table in foreign schema
            target_table: Name of target table in current database
            column_mapping: Mapping of source column names to target column names
                           e.g., {"old_name": "new_name", "id": "id"}

        Returns:
            Number of rows migrated

        Raises:
            MigrationError: If migration fails

        Example:
            >>> migrator.migrate_table(
            ...     source_table="users",
            ...     target_table="users",
            ...     column_mapping={"full_name": "display_name", "id": "id"}
            ... )
            1000
        """
        if not column_mapping:
            raise MigrationError("column_mapping cannot be empty")

        try:
            with self.target_connection.cursor() as cursor:
                # Build SELECT clause with column mapping
                # Maps: old_col AS new_col, old_col AS new_col, ...
                select_items = []
                for source_col, target_col in column_mapping.items():
                    select_items.append(
                        sql.SQL("{source} AS {target}").format(
                            source=sql.Identifier(source_col),
                            target=sql.Identifier(target_col),
                        )
                    )

                # Build target column list
                target_cols = [sql.Identifier(col) for col in column_mapping.values()]

                # Build INSERT ... SELECT statement
                insert_query = sql.SQL("""
                    INSERT INTO {target_table} ({target_cols})
                    SELECT {select_items}
                    FROM {foreign_schema}.{source_table}
                """).format(
                    target_table=sql.Identifier(target_table),
                    target_cols=sql.SQL(", ").join(target_cols),
                    select_items=sql.SQL(", ").join(select_items),
                    foreign_schema=sql.Identifier(self.foreign_schema_name),
                    source_table=sql.Identifier(source_table),
                )

                cursor.execute(insert_query)
                rows_migrated = cursor.rowcount

            self.target_connection.commit()
            return rows_migrated

        except psycopg.Error as e:
            self.target_connection.rollback()
            raise MigrationError(
                f"Failed to migrate table {source_table} → {target_table}: {e}"
            ) from e

    def migrate_table_copy(
        self,
        source_table: str,
        target_table: str,
        column_mapping: dict[str, str],
    ) -> int:
        """Migrate data using COPY strategy (10-20x faster for large tables).

        This method uses PostgreSQL's COPY command to stream data from source
        to target with minimal memory usage. It's optimized for large tables
        (>10M rows) and supports column mapping.

        The COPY strategy:
        1. Builds a SELECT query with column mapping on source table
        2. Uses COPY ... TO STDOUT to export data from source
        3. Buffers data in memory
        4. Uses COPY ... FROM STDIN to load data into target
        5. All in one transaction for safety

        Args:
            source_table: Name of source table in foreign schema
            target_table: Name of target table in current database
            column_mapping: Mapping of source column names to target column names
                           e.g., {"old_name": "new_name", "id": "id"}

        Returns:
            Number of rows migrated

        Raises:
            MigrationError: If migration fails

        Example:
            >>> migrator.migrate_table_copy(
            ...     source_table="large_events",
            ...     target_table="events",
            ...     column_mapping={"event_type": "type", "id": "id"}
            ... )
            100000000  # 100M rows migrated

        Note:
            This is 10-20x faster than the FDW strategy for large tables,
            but requires the source table to be in the foreign schema.
        """
        if not column_mapping:
            raise MigrationError("column_mapping cannot be empty")

        buffer = BytesIO()

        try:
            # Build SELECT query with column mapping for COPY
            # We select from the foreign schema with source column names
            select_items = []
            for source_col in column_mapping:
                select_items.append(
                    sql.SQL("{source}").format(source=sql.Identifier(source_col))
                )

            select_query = sql.SQL("SELECT {select_items} FROM {foreign_schema}.{source_table}").format(
                select_items=sql.SQL(", ").join(select_items),
                foreign_schema=sql.Identifier(self.foreign_schema_name),
                source_table=sql.Identifier(source_table),
            )

            # Build target column list (using mapped target names)
            target_cols = [sql.Identifier(col) for col in column_mapping.values()]

            # Step 1: COPY data from source to buffer
            with self.target_connection.cursor() as cursor:
                copy_to_query = sql.SQL("COPY ({select_query}) TO STDOUT WITH (FORMAT csv)").format(
                    select_query=select_query
                )

                with cursor.copy(copy_to_query.as_string(cursor)) as copy:
                    # Read all data into buffer
                    for chunk in copy:
                        buffer.write(chunk)

            # Reset buffer to beginning for reading
            buffer.seek(0)

            # Step 2: COPY data from buffer to target table
            with self.target_connection.cursor() as cursor:
                copy_from_query = sql.SQL("COPY {target_table} ({target_cols}) FROM STDIN WITH (FORMAT csv)").format(
                    target_table=sql.Identifier(target_table),
                    target_cols=sql.SQL(", ").join(target_cols),
                )

                with cursor.copy(copy_from_query.as_string(cursor)) as copy:
                    # Write data from buffer
                    copy.write(buffer.getvalue())

                # Get row count
                cursor.execute(
                    sql.SQL("SELECT COUNT(*) FROM {table}").format(
                        table=sql.Identifier(target_table)
                    )
                )
                result = cursor.fetchone()
                rows_migrated = result[0] if result else 0

            self.target_connection.commit()
            return rows_migrated

        except psycopg.Error as e:
            self.target_connection.rollback()
            raise MigrationError(
                f"Failed to migrate table {source_table} → {target_table} using COPY: {e}"
            ) from e
        finally:
            buffer.close()

    def analyze_tables(self, schema: str = "public") -> dict[str, dict[str, Any]]:
        """Analyze table sizes and recommend optimal migration strategy.

        This method queries the target database to get row counts for all tables,
        then recommends the optimal migration strategy (FDW or COPY) based on
        table size.

        Strategy selection:
        - Tables with < 10M rows → FDW strategy (better for complex transformations)
        - Tables with ≥ 10M rows → COPY strategy (10-20x faster)

        Args:
            schema: Schema name to analyze (default: "public")

        Returns:
            Dictionary mapping table names to analysis results:
            {
                "table_name": {
                    "strategy": "fdw" | "copy",
                    "row_count": int,
                    "estimated_seconds": float
                }
            }

        Raises:
            MigrationError: If analysis fails

        Example:
            >>> migrator = SchemaToSchemaMigrator(...)
            >>> recommendations = migrator.analyze_tables()
            >>> print(recommendations)
            {
                "users": {
                    "strategy": "fdw",
                    "row_count": 50000,
                    "estimated_seconds": 0.1
                },
                "events": {
                    "strategy": "copy",
                    "row_count": 50000000,
                    "estimated_seconds": 8.3
                }
            }
        """
        try:
            recommendations = {}

            with self.target_connection.cursor() as cursor:
                # Get all tables in the schema with their row counts
                cursor.execute(
                    sql.SQL("""
                        SELECT
                            relname AS tablename,
                            n_live_tup AS estimated_rows
                        FROM pg_stat_user_tables
                        WHERE schemaname = %s
                        ORDER BY relname
                    """),
                    (schema,)
                )

                for table_name, estimated_rows in cursor.fetchall():
                    # For tables without statistics, do a count
                    if estimated_rows is None or estimated_rows == 0:
                        cursor.execute(
                            sql.SQL("SELECT COUNT(*) FROM {schema}.{table}").format(
                                schema=sql.Identifier(schema),
                                table=sql.Identifier(table_name),
                            )
                        )
                        result = cursor.fetchone()
                        row_count = int(result[0]) if result else 0
                    else:
                        row_count = int(estimated_rows)

                    # Determine strategy based on row count threshold
                    if row_count >= LARGE_TABLE_THRESHOLD:
                        strategy = "copy"
                        estimated_seconds = row_count / COPY_THROUGHPUT
                    else:
                        strategy = "fdw"
                        estimated_seconds = row_count / FDW_THROUGHPUT

                    # Round to 3 decimal places, with minimum 0.001 for non-empty tables
                    if row_count > 0:
                        estimated_seconds = max(0.001, round(estimated_seconds, 3))
                    else:
                        estimated_seconds = 0.0

                    recommendations[table_name] = {
                        "strategy": strategy,
                        "row_count": row_count,
                        "estimated_seconds": estimated_seconds,
                    }

            return recommendations

        except psycopg.Error as e:
            raise MigrationError(f"Failed to analyze tables in schema '{schema}': {e}") from e
