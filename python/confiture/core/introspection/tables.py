"""Schema introspector for existing PostgreSQL databases.

The ``introspect`` wire shape over :func:`confiture.core.live_catalog.read`: the
tables, their columns and the foreign-key graph between them, as the catalog
holds them — ``format_type``'s spelling of a type, a composite foreign key paired
column by column, a reference into another schema.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from confiture.core import live_catalog
from confiture.models.introspection import (
    FKReference,
    IntrospectedColumn,
    IntrospectedTable,
    IntrospectionResult,
    TableHints,
)

if TYPE_CHECKING:
    import psycopg

    from confiture.core.schema_model import Table

#: What ``introspect`` has always meant by a table: an ordinary one, a partition
#: included, a partitioned parent — which holds no rows of its own — not.
_INTROSPECTED_KINDS = ("r",)


class SchemaIntrospector:
    """Introspects an existing PostgreSQL database and returns structured output.

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
        model = live_catalog.read(self._conn, schemas=[schema], kinds=_INTROSPECTED_KINDS)
        tables = [
            _introspected(table, include_hints)
            for table in model.tables.values()
            if all_tables or table.name.startswith("tb_")
        ]

        self._resolve_inbound_fks(tables)

        return IntrospectionResult(
            database=self._get_db_name(),
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


def _introspected(table: Table, include_hints: bool) -> IntrospectedTable:
    """One table in the wire shape; its inbound FKs are filled in afterwards."""
    columns = [
        IntrospectedColumn(
            name=column.name,
            pg_type=column.type_text or "",
            nullable=not column.not_null,
            is_primary_key=column.primary_key,
        )
        for column in table.columns
    ]
    return IntrospectedTable(
        name=table.name,
        columns=columns,
        outbound_fks=_outbound_fks(table),
        inbound_fks=[],
        hints=_detect_hints(columns) if include_hints else None,
    )


def _outbound_fks(table: Table) -> list[FKReference]:
    """The table's foreign keys, one reference per column pair.

    In constraint-name order — the catalog's — then in key order, so a composite
    key pairs its first column with the first column it references. ``to_table``
    is the referenced relation's name without its schema: ``pg_get_constraintdef``
    qualifies it only when ``search_path`` would not find it, and the graph is
    keyed by bare name either way.
    """
    return [
        FKReference(
            from_table=None,
            to_table=(fk.ref_table or "").rpartition(".")[2],
            via_column=via,
            on_column=on,
        )
        for fk in table.constraints_of("foreign_key")
        for via, on in zip(fk.columns, fk.ref_columns, strict=True)
    ]


def _detect_hints(columns: list[IntrospectedColumn]) -> TableHints | None:
    """Detect surrogate-PK / natural-ID naming conventions.

    These are non-prescriptive signals. The caller (agent or developer)
    decides what to do with them.

    Args:
        columns: Columns of the table to inspect.

    Returns:
        TableHints if at least one convention is detected, otherwise None.
    """
    hints = TableHints.of([c.name for c in columns if c.is_primary_key], {c.name for c in columns})
    return hints if hints.surrogate_pk or hints.natural_id else None
