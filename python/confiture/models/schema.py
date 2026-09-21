"""The change set ``migrate diff`` produces: :class:`SchemaChange` and :class:`SchemaDiff`.

What a schema *declares* is ``core/schema_model.py``'s — one model, read by the lint
inventory and compared by the differ. The differ's own model of a table, its
columns, indexes, constraints, enums and sequences lived here and is retired;
importing one of its names says where the model is now.
"""

from dataclasses import dataclass, field
from typing import Any

from confiture.models.warnings import BuildWarning

#: The names this module held before the schema model, and where each went.
_MOVED: dict[str, str] = {
    "Table": "confiture.core.schema_model.Table",
    "Column": "confiture.core.schema_model.Column",
    "Index": "confiture.core.schema_model.Index",
    "EnumType": "confiture.core.schema_model.EnumType",
    "Sequence": "confiture.core.schema_model.Sequence",
    "ForeignKey": 'confiture.core.schema_model.Constraint (kind="foreign_key")',
    "CheckConstraint": 'confiture.core.schema_model.Constraint (kind="check")',
    "UniqueConstraint": 'confiture.core.schema_model.Constraint (kind="unique")',
    "ColumnType": "confiture.core.schema_model.Column.type_key (a canonical type name)",
    "ParsedSchema": "confiture.core.differ.ParsedSchema",
    "qualified_name": "confiture.core.schema_model.qualified_name",
}


def __getattr__(name: str) -> Any:
    """A retired name fails with where it went, rather than a bare ``ImportError``."""
    moved = _MOVED.get(name)
    if moved is not None:
        msg = f"confiture.models.schema.{name} is retired: use {moved}"
        raise ImportError(msg)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


# ``str(SchemaChange)`` per change type; ``name`` comes from ``details``, under the
# one key every kind's ``detail_fn`` writes it to.
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
    "ADD_INDEX": "ADD INDEX {name} ON {table}",
    "DROP_INDEX": "DROP INDEX {name}",
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
            name=details.get("name", ""),
        )


@dataclass
class SchemaDiff:
    """Represents the difference between two schemas."""

    changes: list[SchemaChange] = field(default_factory=list)
    #: Why the diff may not be the whole story: a duplicate definition on
    #: either side, which is not a change but is a reason the comparison read a
    #: tree the build may not produce. Empty when there is nothing to report —
    #: present either way, never absent-on-success.
    warnings: list[BuildWarning] = field(default_factory=list)

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
