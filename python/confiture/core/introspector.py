"""Schema introspector for existing PostgreSQL databases.

Queries pg_catalog (not information_schema) for correctness across all
PostgreSQL 12+ versions, including composite FKs and cross-schema references.
"""

from datetime import UTC, datetime

import psycopg

from confiture.models.introspection import (
    FKReference,
    IntrospectedColumn,
    IntrospectedTable,
    IntrospectionResult,
    TableHints,
)


class SchemaIntrospector:
    """Introspects an existing PostgreSQL database and returns structured output.

    Uses pg_catalog views and functions (format_type, pg_constraint,
    pg_attribute) rather than information_schema to guarantee accurate
    type names and correct FK resolution for all column configurations.

    Args:
        connection: An open psycopg connection to the target database.

    Example:
        >>> with psycopg.connect(db_url) as conn:
        ...     result = SchemaIntrospector(conn).introspect(schema="public")
        ...     print(result.to_dict())
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._conn = connection

    def introspect(
        self,
        schema: str = "public",
        all_tables: bool = False,
        include_hints: bool = True,
    ) -> IntrospectionResult:
        """Introspect all (matching) tables in the given schema.

        Args:
            schema: PostgreSQL schema to introspect (default: ``"public"``).
            all_tables: If False (default), only tables whose names start with
                ``tb_`` are included. If True, all base tables are included.
            include_hints: If True (default), populate the ``hints`` field on
                each table. If False, ``hints`` is always ``None``.

        Returns:
            IntrospectionResult with the full FK graph and column details.
        """
        db_name = self._get_db_name()
        table_names = self._list_tables(schema, all_tables)

        tables = [self._introspect_table(schema, name, include_hints) for name in table_names]

        self._resolve_inbound_fks(tables)

        return IntrospectionResult(
            database=db_name,
            schema=schema,
            introspected_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            tables=tables,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_db_name(self) -> str:
        """Return the current database name."""
        with self._conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            row = cur.fetchone()
            return str(row[0]) if row else "unknown"

    def _list_tables(self, schema: str, all_tables: bool) -> list[str]:
        """Return sorted table names in the schema.

        Args:
            schema: Schema to query.
            all_tables: If False, restrict to ``tb_*`` tables.

        Returns:
            Alphabetically sorted list of table names.
        """
        with self._conn.cursor() as cur:
            if all_tables:
                cur.execute(
                    """
                    SELECT c.relname
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = %s AND c.relkind = 'r'
                    ORDER BY c.relname
                    """,
                    (schema,),
                )
            else:
                cur.execute(
                    """
                    SELECT c.relname
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = %s AND c.relkind = 'r'
                      AND c.relname LIKE 'tb\\_%'
                    ORDER BY c.relname
                    """,
                    (schema,),
                )
            return [row[0] for row in cur.fetchall()]

    def _introspect_table(self, schema: str, table: str, include_hints: bool) -> IntrospectedTable:
        """Build an IntrospectedTable for one table.

        Args:
            schema: Schema containing the table.
            table: Table name.
            include_hints: Whether to populate the hints field.

        Returns:
            IntrospectedTable with columns and outbound FKs populated.
            Inbound FKs are filled in later by _resolve_inbound_fks.
        """
        pk_cols = self._get_primary_keys(schema, table)
        columns = self._get_columns(schema, table, pk_cols)
        outbound_fks = self._get_outbound_fks(schema, table)
        hints = _detect_hints(columns) if include_hints else None

        return IntrospectedTable(
            name=table,
            columns=columns,
            outbound_fks=outbound_fks,
            inbound_fks=[],
            hints=hints,
        )

    def _get_primary_keys(self, schema: str, table: str) -> set[str]:
        """Return the set of primary-key column names for a table.

        Uses pg_index rather than information_schema.table_constraints so that
        the result is always consistent with what pg_attribute reports.

        Args:
            schema: Schema containing the table.
            table: Table name.

        Returns:
            Set of column names that form the primary key (may be empty).
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.attname
                FROM pg_index i
                JOIN pg_class c ON c.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a
                    ON a.attrelid = i.indrelid
                    AND a.attnum = ANY(i.indkey)
                WHERE n.nspname = %s AND c.relname = %s
                  AND i.indisprimary
                """,
                (schema, table),
            )
            return {row[0] for row in cur.fetchall()}

    def _get_columns(self, schema: str, table: str, pk_cols: set[str]) -> list[IntrospectedColumn]:
        """Return columns in ordinal order for a table.

        Uses pg_attribute + format_type() to get accurate PostgreSQL type
        names (e.g. "character varying(255)" not the generic SQL name).

        Args:
            schema: Schema containing the table.
            table: Table name.
            pk_cols: Set of column names that are primary keys.

        Returns:
            List of IntrospectedColumn in ordinal position order.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    a.attname,
                    pg_catalog.format_type(a.atttypid, a.atttypmod),
                    NOT a.attnotnull
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s AND c.relname = %s
                  AND a.attnum > 0 AND NOT a.attisdropped
                ORDER BY a.attnum
                """,
                (schema, table),
            )
            return [
                IntrospectedColumn(
                    name=name,
                    pg_type=pg_type,
                    nullable=nullable,
                    is_primary_key=name in pk_cols,
                )
                for name, pg_type, nullable in cur.fetchall()
            ]

    def _get_outbound_fks(self, schema: str, table: str) -> list[FKReference]:
        """Return FKs declared by this table (pointing to other tables).

        Uses pg_constraint with LATERAL unnest to correctly pair local and
        referenced columns for composite FKs, which information_schema joins
        cannot handle reliably.

        Args:
            schema: Schema containing the table.
            table: Table name.

        Returns:
            List of FKReference with to_table set and from_table as None.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    src_att.attname  AS local_column,
                    tgt_cls.relname  AS referenced_table,
                    tgt_att.attname  AS referenced_column
                FROM pg_constraint con
                JOIN pg_class src_cls ON src_cls.oid = con.conrelid
                JOIN pg_namespace src_ns ON src_ns.oid = src_cls.relnamespace
                JOIN pg_class tgt_cls ON tgt_cls.oid = con.confrelid
                JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS sk(n, ord) ON true
                JOIN pg_attribute src_att
                    ON src_att.attrelid = con.conrelid AND src_att.attnum = sk.n
                JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS tk(n, ord)
                    ON sk.ord = tk.ord
                JOIN pg_attribute tgt_att
                    ON tgt_att.attrelid = con.confrelid AND tgt_att.attnum = tk.n
                WHERE con.contype = 'f'
                  AND src_ns.nspname = %s AND src_cls.relname = %s
                ORDER BY con.conname, sk.ord
                """,
                (schema, table),
            )
            return [
                FKReference(
                    from_table=None,
                    to_table=referenced_table,
                    via_column=local_column,
                    on_column=referenced_column,
                )
                for local_column, referenced_table, referenced_column in cur.fetchall()
            ]

    def _resolve_inbound_fks(self, tables: list[IntrospectedTable]) -> None:
        """Populate inbound_fks on each table by inverting outbound FKs.

        No additional database queries are needed: every outbound FK from
        table A to table B becomes an inbound FK on B.

        Args:
            tables: List of IntrospectedTable objects (mutated in-place).
        """
        index: dict[str, IntrospectedTable] = {t.name: t for t in tables}

        for table in tables:
            for fk in table.outbound_fks:
                target = index.get(fk.to_table or "")
                if target is not None:
                    target.inbound_fks.append(
                        FKReference(
                            from_table=table.name,
                            to_table=None,
                            via_column=fk.via_column,
                            on_column=fk.on_column,
                        )
                    )


def _detect_hints(columns: list[IntrospectedColumn]) -> TableHints | None:
    """Detect surrogate-PK / natural-ID naming conventions.

    These are non-prescriptive signals. The caller (agent or developer)
    decides what to do with them.

    Args:
        columns: Columns of the table to inspect.

    Returns:
        TableHints if at least one convention is detected, otherwise None.
    """
    pk_names = [c.name for c in columns if c.is_primary_key]
    surrogate_pk = next((n for n in pk_names if n.startswith("pk_")), None)

    col_names = {c.name for c in columns}
    natural_id = "id" if "id" in col_names else None

    if surrogate_pk or natural_id:
        return TableHints(surrogate_pk=surrogate_pk, natural_id=natural_id)
    return None
