"""An object dropped and created again in one migration: a replacement, as written.

``DROP VIEW v`` alone destroys an object, and the change set tiers it so. A
migration that drops a view to let a column change pass under it and creates it
again further down replaces the view: nothing is lost that the file does not put
back. The drop takes the tier of the replacement the pair is — a plain view's, or
a materialized view's or a TVIEW's, whose rows are recomputed while readers wait
(#765).

A constraint is paired the same way: ``DROP CONSTRAINT IF EXISTS c`` before ``ADD
CONSTRAINT c`` on the same table is how a generated migration adds a constraint
that a run outside a transaction may have left behind (#785), and the drop takes
the tier of the ``ADD``.

A drop is paired only with a creation of the same kind, by the name **as
written**: loosening a verdict never matches by identity. A ``CASCADE`` drop is
never paired, since what it takes with it is not written.
"""

from dataclasses import replace
from typing import Any

from confiture.core._pglast_enums import member as _pg_member
from confiture.core.change_set.models import _TIER_BY_KIND, ChangeEntry
from confiture.core.ddl_walk import enum_int, relation_parts, tview_calls

_DROP_CASCADE = _pg_member("DropBehavior", "DROP_CASCADE")
_AT_ADD_CONSTRAINT = _pg_member("AlterTableType", "AT_AddConstraint")
_AT_DROP_CONSTRAINT = _pg_member("AlterTableType", "AT_DropConstraint")

#: The drop each creation kind answers, and the replacement the pair is.
_FAMILY: dict[str, str] = {
    "drop_view": "view",
    "create_view": "view",
    "replace_view": "view",
    "drop_materialized_view": "materialized_view",
    "create_materialized_view": "materialized_view",
    "replace_materialized_view": "materialized_view",
    "drop_constraint": "constraint",
    "add_constraint": "constraint",
}

Written = tuple[str, ...]


def _written(node: Any) -> list[Written | None]:
    """The name each entry of *node* is about, as written; ``None`` where it is not paired."""
    kind = type(node).__name__
    if kind == "DropStmt":
        if enum_int(getattr(node, "behavior", None)) == _DROP_CASCADE:
            return [None for _ in node.objects or ()]
        return [
            tuple(str(getattr(part, "sval", part)) for part in getattr(obj, "items", obj) or ())
            for obj in node.objects or ()
        ]
    if kind == "AlterTableStmt":
        table = relation_parts(node.relation)
        return [_constraint(table, cmd) for cmd in node.cmds or ()]
    if kind == "ViewStmt":
        return [_parts(relation_parts(node.view))]
    if kind == "CreateTableAsStmt":
        return [_parts(relation_parts(getattr(node.into, "rel", None)))]
    if kind == "SelectStmt":
        return [
            _parts((call.schema, call.name)) if call.name else None for call in tview_calls(node)
        ]
    return []


def _constraint(table: tuple[str | None, str | None], cmd: Any) -> Written | None:
    """``(schema, table, constraint)`` as written for a constraint's drop or add; ``None`` otherwise."""
    subtype = enum_int(cmd.subtype)
    if subtype == _AT_DROP_CONSTRAINT:
        if enum_int(getattr(cmd, "behavior", None)) == _DROP_CASCADE:
            return None
        name = cmd.name
    elif subtype == _AT_ADD_CONSTRAINT:
        name = getattr(cmd.def_, "conname", None)
    else:
        return None
    written = _parts(table)
    return (*written, name) if written and name else None


def _parts(written: tuple[str | None, str | None]) -> Written | None:
    schema, name = written
    if name is None:
        return None
    return (schema, name) if schema else (name,)


class Rebuilt:
    """The drops of one file still waiting for their creation, by kind and name as written."""

    def __init__(self) -> None:
        self.waiting: dict[tuple[str, Written], list[int]] = {}

    def read(self, node: Any, entries: list[ChangeEntry], found: list[ChangeEntry]) -> None:
        """Pair *found*, *node*'s entries about to follow *entries*, with the drops before them."""
        names = _written(node)
        if len(names) != len(found):
            return
        for at, (entry, name) in enumerate(zip(found, names, strict=True), start=len(entries)):
            family = _FAMILY.get(entry.kind)
            if family is None or name is None:
                continue
            if entry.kind.startswith("drop_"):
                self.waiting.setdefault((family, name), []).append(at)
                continue
            tier = entry.tier if family == "constraint" else _TIER_BY_KIND[f"replace_{family}"]
            for dropped in self.waiting.pop((family, name), []):
                entries[dropped] = replace(
                    entries[dropped],
                    tier=tier,
                    detail=f"{entries[dropped].detail} — created again in the same file",
                )
