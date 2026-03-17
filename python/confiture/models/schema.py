"""Data models for schema representation.

These models represent database schema objects (tables, columns, indexes, etc.)
in a structured format for diff detection and comparison.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ColumnType(str, Enum):
    """PostgreSQL column types."""

    # Integer types
    SMALLINT = "SMALLINT"
    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    SERIAL = "SERIAL"
    BIGSERIAL = "BIGSERIAL"

    # Numeric types
    NUMERIC = "NUMERIC"
    DECIMAL = "DECIMAL"
    REAL = "REAL"
    DOUBLE_PRECISION = "DOUBLE PRECISION"

    # Text types
    VARCHAR = "VARCHAR"
    CHAR = "CHAR"
    TEXT = "TEXT"

    # Boolean
    BOOLEAN = "BOOLEAN"

    # Date/Time
    DATE = "DATE"
    TIME = "TIME"
    TIMESTAMP = "TIMESTAMP"
    TIMESTAMPTZ = "TIMESTAMPTZ"

    # UUID
    UUID = "UUID"

    # JSON
    JSON = "JSON"
    JSONB = "JSONB"

    # Binary
    BYTEA = "BYTEA"

    # Network types
    CIDR = "CIDR"
    INET = "INET"
    MACADDR = "MACADDR"
    MACADDR8 = "MACADDR8"

    # Money
    MONEY = "MONEY"

    # Bit strings
    BIT = "BIT"
    VARBIT = "VARBIT"

    # Text search
    TSVECTOR = "TSVECTOR"
    TSQUERY = "TSQUERY"

    # XML
    XML = "XML"

    # Range types
    INT4RANGE = "INT4RANGE"
    INT8RANGE = "INT8RANGE"
    NUMRANGE = "NUMRANGE"
    TSRANGE = "TSRANGE"
    TSTZRANGE = "TSTZRANGE"
    DATERANGE = "DATERANGE"

    # Unknown/Custom
    UNKNOWN = "UNKNOWN"


@dataclass
class Column:
    """Represents a database column."""

    name: str
    type: ColumnType
    nullable: bool = True
    default: str | None = None
    primary_key: bool = False
    unique: bool = False
    length: int | None = None  # For VARCHAR(n), etc.
    raw_sql_type: str | None = field(default=None, compare=False, hash=False)

    def __eq__(self, other: object) -> bool:
        """Compare columns for equality."""
        if not isinstance(other, Column):
            return NotImplemented
        return (
            self.name == other.name
            and self.type == other.type
            and self.nullable == other.nullable
            and self.default == other.default
            and self.primary_key == other.primary_key
            and self.unique == other.unique
            and self.length == other.length
        )

    def __hash__(self) -> int:
        """Make column hashable for use in sets."""
        return hash(
            (
                self.name,
                self.type,
                self.nullable,
                self.default,
                self.primary_key,
                self.unique,
                self.length,
            )
        )


@dataclass
class Index:
    """Represents a database index."""

    name: str
    table: str
    columns: list[str]
    unique: bool = False
    where: str | None = None  # partial index predicate


@dataclass
class ForeignKey:
    """Represents a foreign key constraint."""

    name: str
    table: str
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    on_delete: str | None = None
    on_update: str | None = None


@dataclass
class CheckConstraint:
    """Represents a CHECK constraint."""

    name: str
    table: str
    expression: str


@dataclass
class UniqueConstraint:
    """Represents a UNIQUE constraint."""

    name: str
    table: str
    columns: list[str]


@dataclass
class EnumType:
    """Represents a CREATE TYPE ... AS ENUM."""

    name: str
    schema: str | None = None
    values: list[str] = field(default_factory=list)


@dataclass
class Sequence:
    """Represents a CREATE SEQUENCE."""

    name: str
    schema: str | None = None
    start: int = 1
    increment: int = 1
    min_value: int | None = None
    max_value: int | None = None


@dataclass
class ParsedSchema:
    """Result of parsing a full SQL DDL string."""

    tables: list["Table"] = field(default_factory=list)
    enum_types: list[EnumType] = field(default_factory=list)
    sequences: list[Sequence] = field(default_factory=list)


@dataclass
class Table:
    """Represents a database table."""

    name: str
    columns: list[Column] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    check_constraints: list[CheckConstraint] = field(default_factory=list)
    unique_constraints: list[UniqueConstraint] = field(default_factory=list)

    def get_column(self, name: str) -> Column | None:
        """Get column by name."""
        for col in self.columns:
            if col.name == name:
                return col
        return None

    def has_column(self, name: str) -> bool:
        """Check if table has column."""
        return self.get_column(name) is not None

    def __eq__(self, other: object) -> bool:
        """Compare tables for equality."""
        if not isinstance(other, Table):
            return NotImplemented
        return (
            self.name == other.name
            and self.columns == other.columns
            and self.indexes == other.indexes
            and self.foreign_keys == other.foreign_keys
            and self.check_constraints == other.check_constraints
            and self.unique_constraints == other.unique_constraints
        )


@dataclass
class Schema:
    """Represents a complete database schema."""

    tables: list[Table] = field(default_factory=list)

    def get_table(self, name: str) -> Table | None:
        """Get table by name."""
        for table in self.tables:
            if table.name == name:
                return table
        return None

    def has_table(self, name: str) -> bool:
        """Check if schema has table."""
        return self.get_table(name) is not None

    def table_names(self) -> list[str]:
        """Get list of all table names."""
        return [table.name for table in self.tables]


@dataclass
class SchemaChange:
    """Represents a single change between two schemas."""

    type: str  # ADD_TABLE, DROP_TABLE, ADD_COLUMN, etc.
    table: str | None = None
    column: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        """String representation of change."""
        if self.type == "ADD_TABLE":
            return f"ADD TABLE {self.table}"
        elif self.type == "DROP_TABLE":
            return f"DROP TABLE {self.table}"
        elif self.type == "RENAME_TABLE":
            return f"RENAME TABLE {self.old_value} TO {self.new_value}"
        elif self.type == "ADD_COLUMN":
            return f"ADD COLUMN {self.table}.{self.column}"
        elif self.type == "DROP_COLUMN":
            return f"DROP COLUMN {self.table}.{self.column}"
        elif self.type == "RENAME_COLUMN":
            return f"RENAME COLUMN {self.table}.{self.old_value} TO {self.new_value}"
        elif self.type == "CHANGE_COLUMN_TYPE":
            return f"CHANGE COLUMN TYPE {self.table}.{self.column} FROM {self.old_value} TO {self.new_value}"
        elif self.type == "CHANGE_COLUMN_NULLABLE":
            return f"CHANGE COLUMN NULLABLE {self.table}.{self.column} FROM {self.old_value} TO {self.new_value}"
        elif self.type == "CHANGE_COLUMN_DEFAULT":
            return f"CHANGE COLUMN DEFAULT {self.table}.{self.column}"
        elif self.type == "ADD_INDEX":
            d = self.details or {}
            return f"ADD INDEX {d.get('index_name', '')} ON {self.table}"
        elif self.type == "DROP_INDEX":
            d = self.details or {}
            return f"DROP INDEX {d.get('index_name', '')}"
        elif self.type == "ADD_FOREIGN_KEY":
            d = self.details or {}
            return f"ADD FOREIGN KEY {d.get('name', '')} ON {self.table}"
        elif self.type == "DROP_FOREIGN_KEY":
            d = self.details or {}
            return f"DROP FOREIGN KEY {d.get('name', '')}"
        elif self.type == "ADD_CHECK_CONSTRAINT":
            d = self.details or {}
            return f"ADD CHECK CONSTRAINT {d.get('name', '')} ON {self.table}"
        elif self.type == "DROP_CHECK_CONSTRAINT":
            d = self.details or {}
            return f"DROP CHECK CONSTRAINT {d.get('name', '')}"
        elif self.type == "ADD_UNIQUE_CONSTRAINT":
            d = self.details or {}
            return f"ADD UNIQUE CONSTRAINT {d.get('name', '')} ON {self.table}"
        elif self.type == "DROP_UNIQUE_CONSTRAINT":
            d = self.details or {}
            return f"DROP UNIQUE CONSTRAINT {d.get('name', '')}"
        elif self.type == "ADD_ENUM_TYPE":
            return f"ADD ENUM TYPE {self.table}"
        elif self.type == "DROP_ENUM_TYPE":
            return f"DROP ENUM TYPE {self.table}"
        elif self.type == "CHANGE_ENUM_VALUES":
            return f"CHANGE ENUM VALUES {self.table}"
        elif self.type == "ADD_SEQUENCE":
            return f"ADD SEQUENCE {self.table}"
        elif self.type == "DROP_SEQUENCE":
            return f"DROP SEQUENCE {self.table}"
        else:
            return f"{self.type}: {self.table}.{self.column if self.column else ''}"


@dataclass
class SchemaDiff:
    """Represents the difference between two schemas."""

    changes: list[SchemaChange] = field(default_factory=list)

    def has_changes(self) -> bool:
        """Check if there are any changes."""
        return len(self.changes) > 0

    def count_by_type(self, change_type: str) -> int:
        """Count changes of a specific type."""
        return sum(1 for c in self.changes if c.type == change_type)

    def __str__(self) -> str:
        """String representation of diff."""
        if not self.has_changes():
            return "No changes detected"
        return "\n".join(str(c) for c in self.changes)
