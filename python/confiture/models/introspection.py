"""Data models for schema introspection output.

These models represent the structured output of the `confiture introspect`
command: tables, columns, types, constraints, and the FK relationship graph.
"""

import dataclasses
from typing import Any


@dataclasses.dataclass
class IntrospectedColumn:
    """A single column in an introspected table.

    Attributes:
        name: Column name.
        pg_type: PostgreSQL type as reported by format_type() (e.g. "bigint",
            "character varying(255)", "timestamp without time zone").
        nullable: True if the column allows NULL.
        is_primary_key: True if the column is part of the primary key.
    """

    name: str
    pg_type: str
    nullable: bool
    is_primary_key: bool


@dataclasses.dataclass
class FKReference:
    """A single foreign-key relationship, from one table to another.

    Used in both directions:
    - outbound_fks: ``from_table`` is None; ``to_table`` is set.
    - inbound_fks: ``to_table`` is None; ``from_table`` is set.

    Attributes:
        from_table: Table that declares the FK (set on inbound references).
        to_table: Table being referenced (set on outbound references).
        via_column: The FK column on the declaring table.
        on_column: The referenced column on the target table.
    """

    from_table: str | None
    to_table: str | None
    via_column: str
    on_column: str


@dataclasses.dataclass
class TableHints:
    """Non-prescriptive naming-convention hints detected in the table.

    These are heuristic signals, not authoritative facts. Agents and developers
    decide what to do with them.

    Attributes:
        surrogate_pk: First primary-key column whose name starts with ``pk_``,
            if any.
        natural_id: The column named ``id`` if present, regardless of type.
    """

    surrogate_pk: str | None
    natural_id: str | None


@dataclasses.dataclass
class IntrospectedTable:
    """Complete introspection result for a single table.

    Attributes:
        name: Table name (without schema prefix).
        columns: Ordered list of columns (ordinal position from pg_attribute).
        outbound_fks: FK relationships this table declares (pointing outward).
        inbound_fks: FK relationships other tables declare pointing here.
        hints: Detected naming-convention signals, or None if none detected.
    """

    name: str
    columns: list[IntrospectedColumn]
    outbound_fks: list[FKReference]
    inbound_fks: list[FKReference]
    hints: TableHints | None


@dataclasses.dataclass
class IntrospectionResult:
    """Top-level result of a `confiture introspect` run.

    Attributes:
        database: Database name as reported by PostgreSQL.
        schema: Schema that was introspected.
        introspected_at: ISO 8601 UTC timestamp of the introspection.
        tables: All introspected tables, sorted alphabetically.
    """

    database: str
    schema: str
    introspected_at: str
    tables: list[IntrospectedTable]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON/YAML output."""
        return dataclasses.asdict(self)
