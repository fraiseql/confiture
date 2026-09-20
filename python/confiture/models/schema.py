"""Data models for schema representation.

These models represent database schema objects (tables, columns, indexes, etc.)
in a structured format for diff detection and comparison.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def qualified_name(schema: str | None, name: str) -> str:
    """The object's name as the schema file spells it.

    ``tenant.t`` when the author wrote a schema, ``t`` when they did not — never
    an invented ``public.``. This is the *spelling*, which is what a finding
    prints and what generated DDL says; the *identity* that decides whether two
    statements are one object folds the missing schema to
    :data:`~confiture.core.linting.inventory.DEFAULT_SCHEMA` and lives in
    ``core.differ._identity``. The two are deliberately different: a project
    whose ``search_path`` is not ``public`` would have its DDL rewritten into
    another schema by a qualifier confiture invented.
    """
    return f"{schema}.{name}" if schema else name


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
    #: The objects compared by definition rather than by structure (#288) —
    #: views, and in later phases everything else a schema tree defines. Keyed
    #: by what makes two ``CREATE`` statements the same object; the value
    #: carries the definition, so a redefinition in place is visible. Typed
    #: loosely here because ``core.ddl_objects`` imports this module.
    objects: dict[Any, Any] = field(default_factory=dict)


@dataclass
class Table:
    """Represents a database table.

    ``name`` is the relation's own name as pglast folded it; ``schema`` is the
    qualifier the statement wrote, and ``None`` when it wrote none. The pair is
    the identity — ``tenant.t`` and ``etl.t`` are two tables (#313) — while
    :attr:`qualified` is the spelling a finding prints.
    """

    name: str
    schema: str | None = None
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

    @property
    def qualified(self) -> str:
        """The table as the schema file names it — see :func:`qualified_name`."""
        return qualified_name(self.schema, self.name)

    __hash__ = None  # mutable; equality is structural

    def __eq__(self, other: object) -> bool:
        """Compare tables for equality."""
        if not isinstance(other, Table):
            return NotImplemented
        return (
            self.name == other.name
            and self.schema == other.schema
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


# ``str(SchemaChange)`` per change type; ``name`` / ``index_name`` come from ``details``.
_CHANGE_TEMPLATES: dict[str, str] = {
    "ADD_TABLE": "ADD TABLE {table}",
    "DROP_TABLE": "DROP TABLE {table}",
    "RENAME_TABLE": "RENAME TABLE {old} TO {new}",
    "ADD_COLUMN": "ADD COLUMN {table}.{column}",
    "DROP_COLUMN": "DROP COLUMN {table}.{column}",
    "RENAME_COLUMN": "RENAME COLUMN {table}.{old} TO {new}",
    "CHANGE_COLUMN_TYPE": "CHANGE COLUMN TYPE {table}.{column} FROM {old} TO {new}",
    "CHANGE_COLUMN_NULLABLE": "CHANGE COLUMN NULLABLE {table}.{column} FROM {old} TO {new}",
    "CHANGE_COLUMN_DEFAULT": "CHANGE COLUMN DEFAULT {table}.{column}",
    "ADD_INDEX": "ADD INDEX {index_name} ON {table}",
    "DROP_INDEX": "DROP INDEX {index_name}",
    "ADD_FOREIGN_KEY": "ADD FOREIGN KEY {name} ON {table}",
    "DROP_FOREIGN_KEY": "DROP FOREIGN KEY {name}",
    "ADD_CHECK_CONSTRAINT": "ADD CHECK CONSTRAINT {name} ON {table}",
    "DROP_CHECK_CONSTRAINT": "DROP CHECK CONSTRAINT {name}",
    "ADD_UNIQUE_CONSTRAINT": "ADD UNIQUE CONSTRAINT {name} ON {table}",
    "DROP_UNIQUE_CONSTRAINT": "DROP UNIQUE CONSTRAINT {name}",
    "ADD_ENUM_TYPE": "ADD ENUM TYPE {table}",
    "DROP_ENUM_TYPE": "DROP ENUM TYPE {table}",
    "CHANGE_ENUM_VALUES": "CHANGE ENUM VALUES {table}",
    "ADD_SEQUENCE": "ADD SEQUENCE {table}",
    "DROP_SEQUENCE": "DROP SEQUENCE {table}",
}


@dataclass
class SchemaChange:
    """Represents a single change between two schemas."""

    type: str  # ADD_TABLE, DROP_TABLE, ADD_COLUMN, etc.
    table: str | None = None
    column: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    details: dict[str, Any] | None = None

    def _object_str(self) -> str | None:
        """``ADD TRIGGER public.tb_user.trg_touch`` for a change #288 tracks.

        The keyword travels in ``details`` rather than in a template row per
        kind: there are sixty of those and no one would notice a missing one,
        whereas a change built without its keyword simply falls back.
        """
        details = self.details or {}
        keyword = details.get("keyword")
        if not keyword:
            return None
        verb, _, _ = self.type.partition("_")
        return f"{verb} {keyword} {details.get('name', self.table)}"

    def __str__(self) -> str:
        """String representation of change."""
        template = _CHANGE_TEMPLATES.get(self.type)
        if template is None:
            return self._object_str() or (
                f"{self.type}: {self.table}.{self.column if self.column else ''}"
            )
        details = self.details or {}
        return template.format(
            table=self.table,
            column=self.column,
            old=self.old_value,
            new=self.new_value,
            index_name=details.get("index_name", ""),
            name=details.get("name", ""),
        )


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
