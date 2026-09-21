"""What changed between two schema trees: one variant per kind, closed, and their wire form.

``SchemaDiffer.compare`` returns a :class:`SchemaDiff` whose changes are these
variants and nothing else. A change used to be a string and a dict —
``SchemaChange(type="ADD_COLUMN", details={...})`` — so every reader dispatched on a
string it had to spell correctly and read keys the differ may never have written;
``differ_sql`` read ``details["type"]`` for a column, which the differ never set,
and substituted ``text`` for every added column's type. A variant carries the model
objects themselves (``core/schema_model.py``): an added column *is* a
:class:`~confiture.core.schema_model.Column`.

The names are past participles on purpose. ``core/replica/classifier.py`` names the
*operations read from a migration file* in the imperative — ``CreateTable``,
``AddColumn``, ``DropColumn`` — and these are *differences between two trees*. Eight
shared names in one package would be two taxonomies spelled alike.

The wire is :meth:`to_wire`. Every payload that carries a change — ``confiture diff
--format json``, ``migrate diff``, the accompaniment report, ``migrate validate
--check-git`` — reads the :class:`~confiture.models.schema.WireChange` it returns,
whose six fields and one line are byte-identical to what the string-and-dict change
printed (``tests/integration/test_diff_goldens.py`` and ``test_wire_goldens.py`` hold
that). The wire's ``type`` strings live in this module and in no other.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, ClassVar, get_args

from confiture.core.ddl_objects import OBJECT_KEYWORD
from confiture.core.differ_sql import column_body
from confiture.core.schema_model import (
    Column,
    Constraint,
    EnumType,
    Index,
    ObjectRef,
    Sequence,
    Table,
)
from confiture.models.schema import WireChange
from confiture.models.warnings import BuildWarning

if TYPE_CHECKING:
    from confiture.core.ddl_objects import DDLObject

__all__ = [
    "KINDS",
    "CheckConstraintAdded",
    "CheckConstraintDropped",
    "ColumnAdded",
    "ColumnDefaultChanged",
    "ColumnDropped",
    "ColumnNullabilityChanged",
    "ColumnRenamed",
    "ColumnTypeChanged",
    "EnumTypeAdded",
    "EnumTypeDropped",
    "EnumValuesChanged",
    "ForeignKeyAdded",
    "ForeignKeyDropped",
    "IndexAdded",
    "IndexDropped",
    "ObjectAdded",
    "ObjectDropped",
    "ObjectReplaced",
    "SchemaChange",
    "SchemaDiff",
    "SequenceAdded",
    "SequenceDropped",
    "TableAdded",
    "TableDropped",
    "TableRenamed",
    "UniqueConstraintAdded",
    "UniqueConstraintDropped",
    "column_definition",
    "written_type",
]


# ---------------------------------------------------------------------------
# The serialisation of a model object, as the wire has always carried it
# ---------------------------------------------------------------------------

#: What a column with no written type is called in a change — none from a parse.
_UNKNOWN_TYPE = "UNKNOWN"


def written_type(column: Column) -> str:
    """The column's type as generated DDL writes it."""
    return column.raw_sql_type or column.type_key or _UNKNOWN_TYPE


def _column_detail(column: Column) -> dict[str, Any]:
    """One column in the shape ``DifferSQLGenerator`` renders it from.

    Identity and generation are present only on a column that has them, so an
    ordinary column's details read exactly as they always have.
    """
    detail: dict[str, Any] = {
        "name": column.folded,
        "type": written_type(column),
        "nullable": not column.not_null,
        "default": column.default,
    }
    if column.identity is not None:
        detail["identity"] = column.identity
    if column.generated is not None:
        detail["generated"] = column.generated
        detail["generated_kind"] = column.generated_kind
    return detail


def column_definition(column: Column) -> str:
    """The column's definition without its name — what ``ADD COLUMN`` takes after the name."""
    return column_body(_column_detail(column))


def _foreign_key_detail(fk: Constraint) -> dict[str, Any]:
    return {
        "kind": "FOREIGN KEY",
        "name": fk.name,
        "columns": list(fk.columns),
        "ref_table": fk.ref_table or "",
        "ref_columns": list(fk.ref_columns),
        "on_delete": fk.on_delete,
        "on_update": fk.on_update,
    }


def _unique_detail(uc: Constraint) -> dict[str, Any]:
    return {"kind": "UNIQUE", "name": uc.name, "columns": list(uc.columns)}


def _check_detail(cc: Constraint) -> dict[str, Any]:
    return {"kind": "CHECK", "name": cc.name, "expression": cc.expression}


def _table_details(table: Table) -> dict[str, Any]:
    """A table's columns and constraints, in the shape a ``CREATE TABLE`` is rendered from.

    The constraints travel with the columns: a ``DROP_TABLE`` down recreates the
    table from exactly these, so a table that came back without its foreign keys
    was a table that came back wrong. The primary key is emitted at table level
    rather than on the column so that a composite one has somewhere to go.
    """
    constraints: list[dict[str, Any]] = [
        {
            "kind": "PRIMARY KEY",
            "name": "",
            "columns": [column.folded for column in table.columns if column.primary_key],
        }
    ]
    constraints.extend(_foreign_key_detail(fk) for fk in table.constraints_of("foreign_key"))
    constraints.extend(_unique_detail(uc) for uc in table.constraints_of("unique"))
    constraints.extend(_check_detail(cc) for cc in table.constraints_of("check"))
    return {
        "columns": [_column_detail(column) for column in table.columns],
        "constraints": [c for c in constraints if c.get("columns") or c.get("expression")],
    }


def _nullable(value: bool) -> str:
    return "true" if value else "false"


# ---------------------------------------------------------------------------
# The variants
# ---------------------------------------------------------------------------


class _Change(ABC):
    """What every variant answers the same way: its wire form and its one line.

    ``WIRE`` is the kind as the wire spells it and ``TEMPLATE`` the line
    ``str(change)`` prints; :meth:`_wire_fields` is the rest of the wire, which is
    the one thing each variant has to say about itself.
    """

    __slots__ = ()

    WIRE: ClassVar[str]
    TEMPLATE: ClassVar[str]

    @abstractmethod
    def _wire_fields(self) -> dict[str, Any]:
        """``table``, ``column``, ``old_value``, ``new_value`` and ``details``, where set."""

    def _wire_type(self) -> str:
        return self.WIRE

    def _text(self, wire: WireChange) -> str:
        details = wire.details or {}
        return self.TEMPLATE.format(
            table=wire.table,
            column=wire.column,
            old=wire.old_value,
            new=wire.new_value,
            name=details.get("name", ""),
        )

    def to_wire(self) -> WireChange:
        """The change as every JSON payload carries it."""
        wire = WireChange(type=self._wire_type(), **self._wire_fields())
        return replace(wire, text=self._text(wire))

    def __str__(self) -> str:
        return str(self.to_wire())


@dataclass(frozen=True)
class TableAdded(_Change):
    """A table only the new tree declares."""

    WIRE: ClassVar[str] = "ADD_TABLE"
    TEMPLATE: ClassVar[str] = "ADD TABLE {table}"

    table: Table

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table.qualified, "details": _table_details(self.table)}


@dataclass(frozen=True)
class TableDropped(_Change):
    """A table only the old tree declares — carried whole, so a down can recreate it."""

    WIRE: ClassVar[str] = "DROP_TABLE"
    TEMPLATE: ClassVar[str] = "DROP TABLE {table}"

    table: Table

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table.qualified, "details": _table_details(self.table)}


@dataclass(frozen=True)
class TableRenamed(_Change):
    """One table under two names, in one schema.

    Both tables travel so the up and the down each have the spelling and the bare
    name they need: ``ALTER TABLE a.t RENAME TO a.t2`` is a syntax error, since
    the target of a ``RENAME`` is a bare name.
    """

    WIRE: ClassVar[str] = "RENAME_TABLE"
    TEMPLATE: ClassVar[str] = "RENAME TABLE {old} TO {new}"

    old: Table
    new: Table

    def _wire_fields(self) -> dict[str, Any]:
        return {
            "table": self.old.qualified,
            "old_value": self.old.qualified,
            "new_value": self.new.qualified,
            "details": {"old_name": self.old.name, "new_name": self.new.name},
        }


@dataclass(frozen=True)
class ColumnAdded(_Change):
    """A column only the new tree declares, on a table both hold.

    ``table`` is the table's **spelling** — what a finding prints and what
    generated DDL alters — never an identity.
    """

    WIRE: ClassVar[str] = "ADD_COLUMN"
    TEMPLATE: ClassVar[str] = "ADD COLUMN {table}.{column}"

    table: str
    column: Column

    def _wire_fields(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "column": self.column.folded,
            "new_value": column_definition(self.column),
        }


@dataclass(frozen=True)
class ColumnDropped(_Change):
    """A column only the old tree declares — carried whole, so a down can restore it."""

    WIRE: ClassVar[str] = "DROP_COLUMN"
    TEMPLATE: ClassVar[str] = "DROP COLUMN {table}.{column}"

    table: str
    column: Column

    def _wire_fields(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "column": self.column.folded,
            "old_value": column_definition(self.column),
        }


@dataclass(frozen=True)
class ColumnRenamed(_Change):
    """One column under two names, on one table."""

    WIRE: ClassVar[str] = "RENAME_COLUMN"
    TEMPLATE: ClassVar[str] = "RENAME COLUMN {table}.{old} TO {new}"

    table: str
    old: str
    new: str

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "old_value": self.old, "new_value": self.new}


@dataclass(frozen=True)
class ColumnTypeChanged(_Change):
    """A column whose type differs, typmod included — both declarations travel."""

    WIRE: ClassVar[str] = "CHANGE_COLUMN_TYPE"
    TEMPLATE: ClassVar[str] = "CHANGE COLUMN TYPE {table}.{column} FROM {old} TO {new}"

    table: str
    old: Column
    new: Column

    def _wire_fields(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "column": self.old.folded,
            "old_value": written_type(self.old),
            "new_value": written_type(self.new),
        }


@dataclass(frozen=True)
class ColumnNullabilityChanged(_Change):
    """A column that became nullable, or stopped being; ``nullable`` is the new tree's."""

    WIRE: ClassVar[str] = "CHANGE_COLUMN_NULLABLE"
    TEMPLATE: ClassVar[str] = "CHANGE COLUMN NULLABLE {table}.{column} FROM {old} TO {new}"

    table: str
    column: str
    nullable: bool

    def _wire_fields(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "column": self.column,
            "old_value": _nullable(not self.nullable),
            "new_value": _nullable(self.nullable),
        }


@dataclass(frozen=True)
class ColumnDefaultChanged(_Change):
    """A column whose default differs; ``None`` is no default."""

    WIRE: ClassVar[str] = "CHANGE_COLUMN_DEFAULT"
    TEMPLATE: ClassVar[str] = "CHANGE COLUMN DEFAULT {table}.{column}"

    table: str
    column: str
    old: str | None
    new: str | None

    def _wire_fields(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "column": self.column,
            "old_value": self.old or None,
            "new_value": self.new or None,
        }


def _index_detail(index: Index) -> dict[str, Any]:
    return {"name": index.name, "columns": list(index.columns), "unique": index.unique}


@dataclass(frozen=True)
class IndexAdded(_Change):
    """An index only the new tree declares on a table both hold."""

    WIRE: ClassVar[str] = "ADD_INDEX"
    TEMPLATE: ClassVar[str] = "ADD INDEX {name} ON {table}"

    table: str
    index: Index

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "details": _index_detail(self.index)}


@dataclass(frozen=True)
class IndexDropped(_Change):
    """An index only the old tree declares on a table both hold."""

    WIRE: ClassVar[str] = "DROP_INDEX"
    TEMPLATE: ClassVar[str] = "DROP INDEX {name}"

    table: str
    index: Index

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "details": _index_detail(self.index)}


def _fk_wire(fk: Constraint) -> dict[str, Any]:
    return {key: value for key, value in _foreign_key_detail(fk).items() if key != "kind"}


@dataclass(frozen=True)
class ForeignKeyAdded(_Change):
    """A foreign key only the new tree declares."""

    WIRE: ClassVar[str] = "ADD_FOREIGN_KEY"
    TEMPLATE: ClassVar[str] = "ADD FOREIGN KEY {name} ON {table}"

    table: str
    constraint: Constraint

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "details": _fk_wire(self.constraint)}


@dataclass(frozen=True)
class ForeignKeyDropped(_Change):
    """A foreign key only the old tree declares."""

    WIRE: ClassVar[str] = "DROP_FOREIGN_KEY"
    TEMPLATE: ClassVar[str] = "DROP FOREIGN KEY {name}"

    table: str
    constraint: Constraint

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "details": _fk_wire(self.constraint)}


def _check_wire(cc: Constraint) -> dict[str, Any]:
    return {"name": cc.name, "expression": cc.expression}


@dataclass(frozen=True)
class CheckConstraintAdded(_Change):
    """A CHECK only the new tree declares, or one whose predicate changed (after a drop)."""

    WIRE: ClassVar[str] = "ADD_CHECK_CONSTRAINT"
    TEMPLATE: ClassVar[str] = "ADD CHECK CONSTRAINT {name} ON {table}"

    table: str
    constraint: Constraint

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "details": _check_wire(self.constraint)}


@dataclass(frozen=True)
class CheckConstraintDropped(_Change):
    """A CHECK only the old tree declares, or one whose predicate changed (before an add)."""

    WIRE: ClassVar[str] = "DROP_CHECK_CONSTRAINT"
    TEMPLATE: ClassVar[str] = "DROP CHECK CONSTRAINT {name}"

    table: str
    constraint: Constraint

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "details": _check_wire(self.constraint)}


def _unique_wire(uc: Constraint) -> dict[str, Any]:
    return {"name": uc.name, "columns": list(uc.columns)}


@dataclass(frozen=True)
class UniqueConstraintAdded(_Change):
    """A UNIQUE constraint only the new tree declares."""

    WIRE: ClassVar[str] = "ADD_UNIQUE_CONSTRAINT"
    TEMPLATE: ClassVar[str] = "ADD UNIQUE CONSTRAINT {name} ON {table}"

    table: str
    constraint: Constraint

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "details": _unique_wire(self.constraint)}


@dataclass(frozen=True)
class UniqueConstraintDropped(_Change):
    """A UNIQUE constraint only the old tree declares."""

    WIRE: ClassVar[str] = "DROP_UNIQUE_CONSTRAINT"
    TEMPLATE: ClassVar[str] = "DROP UNIQUE CONSTRAINT {name}"

    table: str
    constraint: Constraint

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "details": _unique_wire(self.constraint)}


@dataclass(frozen=True)
class EnumTypeAdded(_Change):
    """An enum type only the new tree declares."""

    WIRE: ClassVar[str] = "ADD_ENUM_TYPE"
    TEMPLATE: ClassVar[str] = "ADD ENUM TYPE {table}"

    enum: EnumType

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.enum.qualified}


@dataclass(frozen=True)
class EnumTypeDropped(_Change):
    """An enum type only the old tree declares."""

    WIRE: ClassVar[str] = "DROP_ENUM_TYPE"
    TEMPLATE: ClassVar[str] = "DROP ENUM TYPE {table}"

    enum: EnumType

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.enum.qualified}


@dataclass(frozen=True)
class EnumValuesChanged(_Change):
    """An enum both trees declare with different labels; each list is sorted."""

    WIRE: ClassVar[str] = "CHANGE_ENUM_VALUES"
    TEMPLATE: ClassVar[str] = "CHANGE ENUM VALUES {table}"

    enum: str
    added: tuple[str, ...]
    removed: tuple[str, ...]

    def _wire_fields(self) -> dict[str, Any]:
        return {
            "table": self.enum,
            "details": {"added_values": list(self.added), "removed_values": list(self.removed)},
        }


@dataclass(frozen=True)
class SequenceAdded(_Change):
    """A sequence only the new tree declares."""

    WIRE: ClassVar[str] = "ADD_SEQUENCE"
    TEMPLATE: ClassVar[str] = "ADD SEQUENCE {table}"

    sequence: Sequence

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.sequence.qualified}


@dataclass(frozen=True)
class SequenceDropped(_Change):
    """A sequence only the old tree declares."""

    WIRE: ClassVar[str] = "DROP_SEQUENCE"
    TEMPLATE: ClassVar[str] = "DROP SEQUENCE {table}"

    sequence: Sequence

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.sequence.qualified}


class _ObjectChange(_Change):
    """The kinds compared by definition (#288): nineteen of them, three verbs.

    A view, a routine, a trigger and the rest are carried as the whole statement
    that creates them (``DDLObject``), keyed by ``ObjectRef``, so one variant per
    verb covers every kind ``ddl_objects.OBJECT_KEYWORD`` names — which is what
    makes this union finite. The wire spells the kind into the type
    (``ADD_VIEW``, ``REPLACE_FUNCTION``), as it always has.
    """

    __slots__ = ()

    VERB: ClassVar[str]
    TEMPLATE: ClassVar[str] = "{verb} {keyword} {name}"

    ref: ObjectRef

    def _wire_type(self) -> str:
        return f"{self.VERB}_{self.ref.kind.upper()}"

    def _details(self) -> dict[str, Any]:
        return {
            "kind": self.ref.kind,
            "name": self.ref.qualified,
            "keyword": self._keyword(),
        }

    def _keyword(self) -> str:
        return OBJECT_KEYWORD.get(self.ref.kind, self.ref.kind.replace("_", " ").upper())

    def _text(self, wire: WireChange) -> str:
        name = (wire.details or {}).get("name", wire.table)
        return self.TEMPLATE.format(verb=self.VERB, keyword=self._keyword(), name=name)


@dataclass(frozen=True)
class ObjectAdded(_ObjectChange):
    """An object only the new tree defines."""

    VERB: ClassVar[str] = "ADD"

    ref: ObjectRef
    obj: DDLObject

    def _wire_fields(self) -> dict[str, Any]:
        return {
            "table": self.ref.qualified,
            "new_value": self.obj.create_sql,
            "details": self._details(),
        }


@dataclass(frozen=True)
class ObjectDropped(_ObjectChange):
    """An object only the old tree defines."""

    VERB: ClassVar[str] = "DROP"

    ref: ObjectRef
    obj: DDLObject

    def _wire_fields(self) -> dict[str, Any]:
        return {
            "table": self.ref.qualified,
            "old_value": self.obj.create_sql,
            "details": self._details(),
        }


@dataclass(frozen=True)
class ObjectReplaced(_ObjectChange):
    """An object both trees define, whose canonical definition differs.

    For a view or a routine that is the entire change a migration has to carry,
    and it is invisible to a structural comparison because nothing about the
    object's shape moved.
    """

    VERB: ClassVar[str] = "REPLACE"

    ref: ObjectRef
    old: DDLObject
    new: DDLObject

    def _wire_fields(self) -> dict[str, Any]:
        return {
            "table": self.ref.qualified,
            "old_value": self.old.create_sql,
            "new_value": self.new.create_sql,
            "details": self._details(),
        }


SchemaChange = (
    TableAdded
    | TableDropped
    | TableRenamed
    | ColumnAdded
    | ColumnDropped
    | ColumnRenamed
    | ColumnTypeChanged
    | ColumnNullabilityChanged
    | ColumnDefaultChanged
    | IndexAdded
    | IndexDropped
    | ForeignKeyAdded
    | ForeignKeyDropped
    | CheckConstraintAdded
    | CheckConstraintDropped
    | UniqueConstraintAdded
    | UniqueConstraintDropped
    | EnumTypeAdded
    | EnumTypeDropped
    | EnumValuesChanged
    | SequenceAdded
    | SequenceDropped
    | ObjectAdded
    | ObjectDropped
    | ObjectReplaced
)
"""One difference between two schema trees. Closed: a new kind is a new variant here."""

#: Every variant, for the guards that must answer for each.
KINDS: frozenset[type[SchemaChange]] = frozenset(get_args(SchemaChange))


@dataclass
class SchemaDiff:
    """The difference between two schemas."""

    changes: list[SchemaChange] = field(default_factory=list)
    #: Why the diff may not be the whole story: a duplicate definition on
    #: either side, which is not a change but is a reason the comparison read a
    #: tree the build may not produce. Empty when there is nothing to report —
    #: present either way, never absent-on-success.
    warnings: list[BuildWarning] = field(default_factory=list)

    def has_changes(self) -> bool:
        """Check if there are any changes."""
        return len(self.changes) > 0

    def wire(self) -> list[WireChange]:
        """Every change as the wire carries it."""
        return [change.to_wire() for change in self.changes]

    def __str__(self) -> str:
        """String representation of diff."""
        if not self.has_changes():
            return "No changes detected"
        return "\n".join(str(c) for c in self.changes)
