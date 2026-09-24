"""What changed between two schema trees: one variant per kind, closed, and their wire form.

``SchemaDiffer.compare`` returns a :class:`SchemaDiff` whose changes are these
variants and nothing else. A variant carries the model objects themselves
(``core/schema_model.py``): an added column *is* a
:class:`~confiture.core.schema_model.Column`. A change spelled as a string and a
dict — ``type="ADD_COLUMN", details={...}`` — would make every reader dispatch on
a string it has to spell correctly and read keys the differ may never have
written: a column's type read from a key nobody set comes back as ``text``.

The names are past participles on purpose. ``core/replica/classifier.py`` names the
*operations read from a migration file* in the imperative — ``CreateTable``,
``AddColumn``, ``DropColumn`` — and these are *differences between two trees*. Eight
shared names in one package would be two taxonomies spelled alike.

The wire is :meth:`to_wire`. Every payload that carries a change — ``confiture diff
--format json``, ``migrate diff``, the accompaniment report, ``migrate validate
--check-git`` — reads the :class:`~confiture.models.schema.WireChange` it returns,
whose six fields and one line are pinned byte for byte by
``tests/integration/test_diff_goldens.py`` and ``test_wire_goldens.py``. The wire's
``type`` strings live in this module and in no other.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import Any, ClassVar, get_args

from confiture.core.ddl_clauses import column_body, column_type
from confiture.core.ddl_objects import OBJECT_KEYWORD, DDLObject
from confiture.core.schema_model import (
    Column,
    Constraint,
    EnumType,
    Index,
    ObjectRef,
    Sequence,
    Table,
    ref_for,
)
from confiture.models.schema import WireChange
from confiture.models.warnings import BuildWarning

__all__ = [
    "KINDS",
    "CheckConstraintAdded",
    "CheckConstraintDropped",
    "ColumnAdded",
    "ColumnChange",
    "ColumnDefaultChanged",
    "ColumnDropped",
    "ColumnNullabilityChanged",
    "ColumnRenamed",
    "ColumnTypeChanged",
    "DefinitionChange",
    "EnumOrSequenceChange",
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
    "TableChange",
    "TableDropped",
    "TableObjectChange",
    "TableRenamed",
    "UniqueConstraintAdded",
    "UniqueConstraintDropped",
    "column_definition",
]


# ---------------------------------------------------------------------------
# The serialisation of a model object, as the wire has always carried it
# ---------------------------------------------------------------------------


def _column_detail(column: Column) -> dict[str, Any]:
    """One column in the shape ``DifferSQLGenerator`` renders it from.

    Identity and generation are present only on a column that has them, so an
    ordinary column's details read exactly as they always have.
    """
    detail: dict[str, Any] = {
        "name": column.folded,
        "type": column_type(column),
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
    return column_body(column)


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
    table from exactly these, and a table that comes back without its foreign keys
    comes back wrong. The primary key is emitted at table level rather than on
    the column so that a composite one has somewhere to go.
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


def _written_ref(kind: str, written: str) -> ObjectRef:
    """The reference of an object a change spells ``schema.name`` or ``name``."""
    schema, _, name = written.rpartition(".")
    return ref_for(kind, schema or None, name)


class _OfTable(_Change):
    """A table added or dropped whole."""

    __slots__ = ()

    table: Table

    @property
    def ref(self) -> ObjectRef:
        """The table's key in the model."""
        return ref_for("table", self.table.schema, self.table.name)


class _OnTable(_Change):
    """A change to what a table holds: a column, an index or a constraint.

    ``table`` is the table's spelling; :attr:`ref` is the key the model holds the
    table under, since a column, an index and a constraint are keyed by nothing
    of their own.
    """

    __slots__ = ()

    table: str

    @property
    def ref(self) -> ObjectRef:
        """The key of the table the change is on."""
        return _written_ref("table", self.table)


class _OfEnum(_Change):
    """An enum type added or dropped whole."""

    __slots__ = ()

    enum: EnumType

    @property
    def ref(self) -> ObjectRef:
        """The type's key in the model."""
        return ref_for("type", self.enum.schema, self.enum.name)


class _OfSequence(_Change):
    """A sequence added or dropped whole."""

    __slots__ = ()

    sequence: Sequence

    @property
    def ref(self) -> ObjectRef:
        """The sequence's key in the model."""
        return ref_for("sequence", self.sequence.schema, self.sequence.name)


@dataclass(frozen=True)
class TableAdded(_OfTable):
    """A table only the new tree declares."""

    WIRE: ClassVar[str] = "ADD_TABLE"
    TEMPLATE: ClassVar[str] = "ADD TABLE {table}"

    table: Table

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table.qualified, "details": _table_details(self.table)}


@dataclass(frozen=True)
class TableDropped(_OfTable):
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

    @property
    def ref(self) -> ObjectRef:
        """The old table's key: the name the wire's ``table`` carries."""
        return ref_for("table", self.old.schema, self.old.name)

    def _wire_fields(self) -> dict[str, Any]:
        return {
            "table": self.old.qualified,
            "old_value": self.old.qualified,
            "new_value": self.new.qualified,
            "details": {"old_name": self.old.name, "new_name": self.new.name},
        }


@dataclass(frozen=True)
class ColumnAdded(_OnTable):
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
class ColumnDropped(_OnTable):
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
class ColumnRenamed(_OnTable):
    """One column under two names, on one table."""

    WIRE: ClassVar[str] = "RENAME_COLUMN"
    TEMPLATE: ClassVar[str] = "RENAME COLUMN {table}.{old} TO {new}"

    table: str
    old: str
    new: str

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "old_value": self.old, "new_value": self.new}


@dataclass(frozen=True)
class ColumnTypeChanged(_OnTable):
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
            "old_value": column_type(self.old),
            "new_value": column_type(self.new),
        }


@dataclass(frozen=True)
class ColumnNullabilityChanged(_OnTable):
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
class ColumnDefaultChanged(_OnTable):
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
class IndexAdded(_OnTable):
    """An index only the new tree declares on a table both hold."""

    WIRE: ClassVar[str] = "ADD_INDEX"
    TEMPLATE: ClassVar[str] = "ADD INDEX {name} ON {table}"

    table: str
    index: Index

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "details": _index_detail(self.index)}


@dataclass(frozen=True)
class IndexDropped(_OnTable):
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
class ForeignKeyAdded(_OnTable):
    """A foreign key only the new tree declares."""

    WIRE: ClassVar[str] = "ADD_FOREIGN_KEY"
    TEMPLATE: ClassVar[str] = "ADD FOREIGN KEY {name} ON {table}"

    table: str
    constraint: Constraint

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "details": _fk_wire(self.constraint)}


@dataclass(frozen=True)
class ForeignKeyDropped(_OnTable):
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
class CheckConstraintAdded(_OnTable):
    """A CHECK only the new tree declares, or one whose predicate changed (after a drop)."""

    WIRE: ClassVar[str] = "ADD_CHECK_CONSTRAINT"
    TEMPLATE: ClassVar[str] = "ADD CHECK CONSTRAINT {name} ON {table}"

    table: str
    constraint: Constraint

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "details": _check_wire(self.constraint)}


@dataclass(frozen=True)
class CheckConstraintDropped(_OnTable):
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
class UniqueConstraintAdded(_OnTable):
    """A UNIQUE constraint only the new tree declares."""

    WIRE: ClassVar[str] = "ADD_UNIQUE_CONSTRAINT"
    TEMPLATE: ClassVar[str] = "ADD UNIQUE CONSTRAINT {name} ON {table}"

    table: str
    constraint: Constraint

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "details": _unique_wire(self.constraint)}


@dataclass(frozen=True)
class UniqueConstraintDropped(_OnTable):
    """A UNIQUE constraint only the old tree declares."""

    WIRE: ClassVar[str] = "DROP_UNIQUE_CONSTRAINT"
    TEMPLATE: ClassVar[str] = "DROP UNIQUE CONSTRAINT {name}"

    table: str
    constraint: Constraint

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.table, "details": _unique_wire(self.constraint)}


@dataclass(frozen=True)
class EnumTypeAdded(_OfEnum):
    """An enum type only the new tree declares."""

    WIRE: ClassVar[str] = "ADD_ENUM_TYPE"
    TEMPLATE: ClassVar[str] = "ADD ENUM TYPE {table}"

    enum: EnumType

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.enum.qualified}


@dataclass(frozen=True)
class EnumTypeDropped(_OfEnum):
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

    @property
    def ref(self) -> ObjectRef:
        """The type's key in the model; ``enum`` is its spelling."""
        return _written_ref("type", self.enum)

    def _wire_fields(self) -> dict[str, Any]:
        return {
            "table": self.enum,
            "details": {"added_values": list(self.added), "removed_values": list(self.removed)},
        }


@dataclass(frozen=True)
class SequenceAdded(_OfSequence):
    """A sequence only the new tree declares."""

    WIRE: ClassVar[str] = "ADD_SEQUENCE"
    TEMPLATE: ClassVar[str] = "ADD SEQUENCE {table}"

    sequence: Sequence

    def _wire_fields(self) -> dict[str, Any]:
        return {"table": self.sequence.qualified}


@dataclass(frozen=True)
class SequenceDropped(_OfSequence):
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
    (``ADD_VIEW``, ``REPLACE_FUNCTION``).
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

#: The union in the five groups a renderer answers for, each a function of its own:
#: a 25-arm ``match`` is past the complexity a function here may have.
TableChange = TableAdded | TableDropped | TableRenamed
ColumnChange = (
    ColumnAdded
    | ColumnDropped
    | ColumnRenamed
    | ColumnTypeChanged
    | ColumnNullabilityChanged
    | ColumnDefaultChanged
)
TableObjectChange = (
    IndexAdded
    | IndexDropped
    | ForeignKeyAdded
    | ForeignKeyDropped
    | CheckConstraintAdded
    | CheckConstraintDropped
    | UniqueConstraintAdded
    | UniqueConstraintDropped
)
EnumOrSequenceChange = (
    EnumTypeAdded | EnumTypeDropped | EnumValuesChanged | SequenceAdded | SequenceDropped
)
DefinitionChange = ObjectAdded | ObjectDropped | ObjectReplaced

#: Every variant, for the guards that must answer for each.
KINDS: frozenset[type[SchemaChange]] = frozenset(get_args(SchemaChange))


#: ``confiture diff --format json``'s ``summary``, in its key order. A rename, a
#: column's type, nullability or default, an enum's labels and every object compared
#: by definition are not counted there.
_SUMMARY: tuple[tuple[str, tuple[type[SchemaChange], ...]], ...] = (
    ("tables_added", (TableAdded,)),
    ("tables_dropped", (TableDropped,)),
    ("tables_renamed", (TableRenamed,)),
    ("columns_added", (ColumnAdded,)),
    ("columns_dropped", (ColumnDropped,)),
    ("indexes_added", (IndexAdded,)),
    ("indexes_dropped", (IndexDropped,)),
    ("foreign_keys_added", (ForeignKeyAdded,)),
    ("foreign_keys_dropped", (ForeignKeyDropped,)),
    ("constraints_added", (CheckConstraintAdded, UniqueConstraintAdded)),
    ("constraints_dropped", (CheckConstraintDropped, UniqueConstraintDropped)),
    ("enum_types_added", (EnumTypeAdded,)),
    ("enum_types_dropped", (EnumTypeDropped,)),
    ("sequences_added", (SequenceAdded,)),
    ("sequences_dropped", (SequenceDropped,)),
)


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

    def summary(self) -> dict[str, int]:
        """How many changes of each counted kind — ``confiture diff``'s ``summary``."""
        return {
            key: sum(isinstance(change, kinds) for change in self.changes)
            for key, kinds in _SUMMARY
        }

    def __str__(self) -> str:
        """String representation of diff."""
        if not self.has_changes():
            return "No changes detected"
        return "\n".join(str(c) for c in self.changes)
