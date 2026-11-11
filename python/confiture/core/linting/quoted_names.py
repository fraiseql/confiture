"""``naming_003`` and ``naming_004``: no identifier holds a dot, or needs quotes (#476, #484).

confiture supports a name only as PostgreSQL writes it bare: lowercase letters,
digits, ``_`` and ``$``, not starting with a digit, not a reserved word. A name
that exists only quoted is an error, and a dot inside one is the worst case, so
it has its own rule: confiture carries some names as ``schema.name`` text, where
the dot reads as the separator, and ``REFERENCES app."a.b"`` would name table
``b`` in schema ``app.a`` to what reads it. Every other name that needs quotes
(``"Order Line"``, ``"MyTable"``, ``"user"``, ``"1st"``) is ``naming_004``'s.
Each is reported once per object, under one rule, and spelled as SQL writes it.

What is read is every name the tree gives: a schema, each relation, type,
sequence and routine, each table's columns, indexes and named constraints. A schema is reported
where it is declared, or — when the tree only ever uses it as a qualifier —
where it is first used, and its objects are not reported again for it.
"""

import string
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from confiture.core.linting.inventory import distinct
from confiture.core.schema_identity import quote_identifier
from confiture.core.schema_model import RelationName

if TYPE_CHECKING:
    from confiture.core.linting.inventory import Inventory, SchemaObject
    from confiture.core.schema_model import SchemaModel, Table, Trigger

_DOT = "."
#: The kinds of object that are relations: what ``diff.exclude`` leaves out, with
#: everything on one (``relation_exclusion.RELATION_KINDS``; a test holds them equal).
_RELATIONS = frozenset({"table", "view", "matview", "tview", "sequence", "foreign_table"})
#: The characters a bare identifier is written with, after the first.
_BARE = frozenset(string.ascii_lowercase + string.digits + "_$")


@dataclass(frozen=True)
class QuotedName:
    """One name that exists only quoted, and where it is given.

    Attributes:
        kind: What it names: ``schema``, ``table``, ``column``, ``index``, …
        dotted: Whether the name holds a dot (``naming_003``) rather than
            needing quotes for another reason (``naming_004``).
        spelled: The object as SQL writes it (``app."a.b"``).
        suggested: The same object under a name that needs no quotes.
        file: The file it is given in, when the lint read files.
        line: The line it is given on.
        relation: The relation the name is, or is on (a column's table, a
            trigger's), in two parts; ``None`` for a schema, a routine or a type.
            What an exclusion reads (#811), so ``spelled`` is never taken apart.
    """

    kind: str
    dotted: bool
    spelled: str
    suggested: str
    file: str | None
    line: int
    relation: RelationName | None = None


def quoted_names(inventory: Inventory) -> Iterator[QuotedName]:
    """Every name *inventory* gives that needs quotes, in the order the tree gives them."""
    reported: set[str] = set()
    for schema in inventory.schemas:
        if needs_quotes(schema.folded_name) and schema.folded_name not in reported:
            reported.add(schema.folded_name)
            yield _named(schema.kind, None, schema.folded_name, schema.file, schema.line)
    for obj in distinct(inventory.objects):
        qualifier = obj.folded_schema
        if qualifier and needs_quotes(qualifier) and qualifier not in reported:
            reported.add(qualifier)
            yield _named("schema", None, qualifier, obj.file, obj.line)
        if needs_quotes(obj.folded_name):
            relation = RelationName(qualifier, obj.folded_name) if obj.kind in _RELATIONS else None
            yield _named(
                obj.kind, _quoted(qualifier), obj.folded_name, obj.file, obj.line, relation
            )
        yield from _parts(obj)


def quoted_trigger_names(triggers: Iterable[Trigger]) -> Iterator[QuotedName]:
    """Every trigger whose name needs quotes; the model holds no line, so ``line`` is 0.

    A trigger is named per table and is not in the lint's inventory, so this is
    the differ's (#487): it refuses a name a generated statement would write.
    """
    for trigger in triggers:
        if needs_quotes(trigger.name):
            on = RelationName(trigger.schema, trigger.table)
            yield _named("trigger", None, trigger.name, None, 0, on)


def quoted_model_names(model: SchemaModel) -> Iterator[QuotedName]:
    """Every name a model holds that needs quotes: what a database read gives.

    The catalog has no file or line, so ``line`` is 0. A schema is reported once,
    and its objects are not reported again for it, as :func:`quoted_names` does.
    """
    reported: set[str] = set()
    named = (
        *((ref, "table") for ref in model.tables),
        *((ref, ref.kind) for ref in model.views),
        *((ref, "tview") for ref in model.tviews),
        *((ref, "type") for ref in model.enum_types),
        *((ref, "sequence") for ref in model.sequences),
        *((ref, ref.kind) for ref in model.routines),
    )
    for ref, kind in named:
        if needs_quotes(ref.schema) and ref.schema not in reported:
            reported.add(ref.schema)
            yield _named("schema", None, ref.schema, None, 0)
        if needs_quotes(ref.name):
            relation = RelationName(ref.schema, ref.name) if kind in _RELATIONS else None
            yield _named(kind, _quoted(ref.schema), ref.name, None, 0, relation)
    for table in model.tables.values():
        yield from _model_parts(table)
    yield from quoted_trigger_names(model.triggers.values())


def _model_parts(table: Table) -> Iterator[QuotedName]:
    """A live table's columns, indexes and constraints whose names need quotes."""
    within = _join(_quoted(table.schema), quote_identifier(table.name))
    on = table.relation
    for column in table.columns:
        if needs_quotes(column.folded):
            yield _named("column", within, column.folded, None, 0, on)
    for index in table.indexes:
        if index.name and needs_quotes(index.name):
            yield _named("index", _quoted(table.schema), index.name, None, 0, on)
    for constraint in table.constraints:
        if constraint.name and needs_quotes(constraint.name):
            yield _named("constraint", within, constraint.name, None, 0, on)


def _parts(table: SchemaObject) -> Iterator[QuotedName]:
    """A table's columns, indexes and constraints whose names need quotes."""
    within = _join(_quoted(table.folded_schema), quote_identifier(table.folded_name))
    on = RelationName(table.folded_schema, table.folded_name)
    for column in table.columns:
        if needs_quotes(column.folded):
            yield _named(
                "column",
                within,
                column.folded,
                column.file or table.file,
                column.line or table.line,
                on,
            )
    for index in table.indexes:
        if index.name and needs_quotes(index.name):
            file, line = table.index_sites.get(index, (table.file, table.line))
            yield _named("index", _quoted(table.folded_schema), index.name, file, line, on)
    for constraint in table.constraints:
        if constraint.name and needs_quotes(constraint.name):
            yield _named("constraint", within, constraint.name, table.file, table.line, on)


def needs_quotes(name: str) -> bool:
    """Whether *name*, as the parser holds it, exists only quoted."""
    return quote_identifier(name) != name


def _named(
    kind: str,
    within: str | None,
    name: str,
    file: str | None,
    line: int,
    relation: RelationName | None = None,
) -> QuotedName:
    """*name*, given in *within*: a schema or a table, already spelled as SQL writes it."""
    dotted = _DOT in name
    return QuotedName(
        kind=kind,
        dotted=dotted,
        spelled=_join(within, quote_identifier(name)),
        suggested=_join(
            within,
            quote_identifier(name.replace(_DOT, "_")) if dotted else _bare(name),
        ),
        file=file,
        line=line,
        relation=relation,
    )


def _bare(name: str) -> str:
    """*name* in snake_case, as a name that needs no quotes.

    Lowercased, an accented letter its base letter, each run of other characters
    one underscore, a leading digit prefixed and a reserved word suffixed with one.
    """
    base = unicodedata.normalize("NFKD", name.lower())
    written = "".join(c if c in _BARE else "" if unicodedata.combining(c) else " " for c in base)
    snake = "_".join(written.split()) or "_"
    if snake[0].isdigit():
        snake = f"_{snake}"
    return snake if not needs_quotes(snake) else f"{snake}_"


def _quoted(schema: str | None) -> str | None:
    """A schema as SQL writes it; ``None`` for a name the author left unqualified."""
    return quote_identifier(schema) if schema else None


def _join(within: str | None, spelled: str) -> str:
    return f"{within}.{spelled}" if within else spelled
