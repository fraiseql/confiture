"""``naming_003``: no identifier holds a dot (#476).

PostgreSQL accepts ``CREATE TABLE app."a.b"``, and the name it holds is ``a.b``.
confiture does not always get the name back: a foreign key's target is carried
as one ``schema.name`` string, and a dot inside a name reads as the separator
there, so ``REFERENCES app."a.b"`` names table ``b`` in schema ``app.a`` to the
differ, to drift and to prep-seed. A dotted name is therefore an error rather
than a matter of style, reported once per object and spelled as SQL writes it.

What is read is every name the tree gives: a schema, each relation, type,
sequence and routine, each table's columns and each index. A schema is reported
where it is declared, or — when the tree only ever uses it as a qualifier —
where it is first used, and its objects are not reported again for it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from confiture.core.linting.inventory import distinct
from confiture.core.schema_identity import quote_identifier

if TYPE_CHECKING:
    from confiture.core.linting.inventory import Inventory, SchemaObject

_DOT = "."


@dataclass(frozen=True)
class DottedName:
    """One name that holds a dot, and where it is given.

    Attributes:
        kind: What it names: ``schema``, ``table``, ``column``, ``index``, …
        spelled: The object as SQL writes it (``app."a.b"``).
        suggested: The same object with each dot in its own name an underscore.
        file: The file it is given in, when the lint read files.
        line: The line it is given on.
    """

    kind: str
    spelled: str
    suggested: str
    file: str | None
    line: int


def dotted_names(inventory: Inventory) -> Iterator[DottedName]:
    """Every name *inventory* gives that holds a dot, in the order the tree gives them."""
    reported: set[str] = set()
    for schema in inventory.schemas:
        if _DOT in schema.folded_name and schema.folded_name not in reported:
            reported.add(schema.folded_name)
            yield _named(schema.kind, None, schema.folded_name, schema.file, schema.line)
    for obj in distinct(inventory.objects):
        qualifier = obj.folded_schema
        if qualifier and _DOT in qualifier and qualifier not in reported:
            reported.add(qualifier)
            yield _named("schema", None, qualifier, obj.file, obj.line)
        if _DOT in obj.folded_name:
            yield _named(obj.kind, _quoted(qualifier), obj.folded_name, obj.file, obj.line)
        yield from _parts(obj)


def _parts(table: SchemaObject) -> Iterator[DottedName]:
    """A table's columns and indexes whose names hold a dot."""
    within = _join(_quoted(table.folded_schema), quote_identifier(table.folded_name))
    for column in table.columns:
        if _DOT in column.folded:
            yield _named("column", within, column.folded, table.file, column.line or table.line)
    for index in table.indexes:
        if index.name and _DOT in index.name:
            line = table.index_lines.get(index, table.line)
            yield _named("index", _quoted(table.folded_schema), index.name, table.file, line)


def _named(kind: str, within: str | None, name: str, file: str | None, line: int) -> DottedName:
    """*name*, given in *within*: a schema or a table, already spelled as SQL writes it."""
    return DottedName(
        kind=kind,
        spelled=_join(within, quote_identifier(name)),
        suggested=_join(within, quote_identifier(name.replace(_DOT, "_"))),
        file=file,
        line=line,
    )


def _quoted(schema: str | None) -> str | None:
    """A schema as SQL writes it; ``None`` for a name the author left unqualified."""
    return quote_identifier(schema) if schema else None


def _join(within: str | None, spelled: str) -> str:
    return f"{within}.{spelled}" if within else spelled
