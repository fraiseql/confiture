"""A schema change as it crosses a wire: :class:`WireChange`.

What changed between two trees is ``core/schema_change.py``'s — a closed union of
variants, each carrying the model objects it is about. Every JSON payload that
carries a change reads the one serialised form this module defines, which a
variant produces with ``to_wire()``: the six fields and the one line that the
string-and-dict ``SchemaChange`` printed before the union, byte for byte.

The names this module held before are retired; importing one says where it went.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

#: The names this module held before the schema model and the change union.
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
    "SchemaChange": (
        "confiture.core.schema_change.SchemaChange, a union of one variant per kind "
        "(its wire form is confiture.models.schema.WireChange)"
    ),
    "SchemaDiff": "confiture.core.schema_change.SchemaDiff",
}


def __getattr__(name: str) -> Any:
    """A retired name fails with where it went, rather than a bare ``ImportError``."""
    moved = _MOVED.get(name)
    if moved is not None:
        msg = f"confiture.models.schema.{name} is retired: use {moved}"
        raise ImportError(msg)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


@dataclass(frozen=True)
class WireChange:
    """One schema change, serialised: what ``--format json`` payloads carry.

    ``type`` is the kind as the wire spells it (``ADD_COLUMN``); ``details`` is a
    serialisation of the variant's model objects. Built by a variant's
    ``to_wire()`` and by nothing else, so a reader of these fields reads what the
    differ decided rather than what a hand-built change happened to say.
    """

    type: str
    table: str | None = None
    column: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    details: dict[str, Any] | None = None
    #: The one line ``str(change)`` prints — ``ADD COLUMN public.t.c``.
    text: str = field(default="", compare=False, repr=False)

    def __str__(self) -> str:
        return self.text


class WireDiff(Protocol):
    """What a result model reads from a diff without naming ``core``: its changes, serialised."""

    def has_changes(self) -> bool: ...

    def wire(self) -> list[WireChange]: ...
