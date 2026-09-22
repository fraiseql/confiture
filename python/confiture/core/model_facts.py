"""What the model says about the objects in it, for a caller that writes into them.

The model (``core/schema_model.py``) is data; this module answers questions over
it — which object a name refers to, which columns a writer supplies, and what each
of those must respect. The first is the ground of the others. DDL writes a reference as it
wrote it — ``REFERENCES catalog.tb_parent`` or ``REFERENCES tb_parent``, a type
``app.status`` or ``status`` — and a reader of the model has to find the object it
means, by the rule identity already follows (#313): a written schema is that
schema, and a missing one is :data:`~confiture.core.schema_identity.DEFAULT_SCHEMA`.
One thing a parse cannot see is ``SET search_path``, so a bare name the default
schema does not hold is the object of that name in whichever *one* schema does —
the wildcard ``inventory.types_match`` applies to a routine's argument types
(#302). Two schemas holding it and neither the default is ambiguous, and
ambiguity resolves to nothing rather than to a guess.
"""

from __future__ import annotations

from collections.abc import Iterable

from confiture.core.ddl_walk import expression_columns
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import (
    SERIAL_TYPES,
    Column,
    ColumnFacts,
    ColumnReference,
    Constraint,
    ObjectRef,
    SchemaModel,
    Table,
    ref_for,
)
from confiture.models.introspection import TableHints


def resolve(refs: Iterable[ObjectRef], written: str) -> ObjectRef | None:
    """The reference among *refs* a name *written* as ``schema.name`` or ``name`` means."""
    schema, _, name = written.rpartition(".")
    candidates = [ref for ref in refs if ref.name == name]
    if schema:
        return next((ref for ref in candidates if ref.schema == schema.lower()), None)
    default = next((ref for ref in candidates if ref.schema == DEFAULT_SCHEMA), None)
    if default is not None or len(candidates) != 1:
        return default
    return candidates[0]


def table_ref(model: SchemaModel, table: ObjectRef | str) -> ObjectRef:
    """*table*'s reference in *model*: a reference it holds, or a name resolved as DDL's is.

    Raises:
        KeyError: when *model* holds no such table.
    """
    found = table if isinstance(table, ObjectRef) else resolve(model.tables, table)
    if found is None or found not in model.tables:
        raise KeyError(f"no table {table!r} in the model")
    return found


def _filled_by_postgresql(column: Column) -> bool:
    """An identity, a generated column or a ``serial`` — however the reader spelled it."""
    serial = (column.raw_sql_type or "").upper() in SERIAL_TYPES
    sequenced = (column.default or "").startswith("nextval(")
    return bool(column.identity or column.generated or serial or sequenced)


def writable_columns(model: SchemaModel, table: ObjectRef | str) -> list[Column]:
    """*table*'s columns a writer supplies, in declaration order.

    Every column but the ones PostgreSQL fills: an identity column (either kind), a
    generated column, and a ``serial`` — which the catalog holds as a ``nextval``
    default. That is the ``pk_*`` / ``id`` split: a writer inserts ``id`` and lets
    PostgreSQL generate ``pk_language``.

    Raises:
        KeyError: when *model* holds no such table.
    """
    columns = model.tables[table_ref(model, table)].columns
    return [column for column in columns if not _filled_by_postgresql(column)]


def _column(table: Table, column: str) -> Column:
    found = table.column(column) or next((c for c in table.columns if c.name == column), None)
    if found is None:
        raise KeyError(f"no column {column!r} in {table.qualified}")
    return found


def _is_unique(table: Table, column: str) -> bool:
    alone = (column,)
    constrained = any(
        c.columns == alone for c in table.constraints if c.kind in {"primary_key", "unique"}
    )
    return constrained or any(
        index.unique and index.where is None and index.columns == alone for index in table.indexes
    )


def _referenced_column(
    model: SchemaModel, target: ObjectRef, fk: Constraint, at: int
) -> str | None:
    if fk.ref_columns:
        return fk.ref_columns[at]
    parent = model.tables.get(target)
    keys = parent.constraints_of("primary_key") if parent is not None else ()
    return keys[0].columns[at] if keys and at < len(keys[0].columns) else None


def _foreign_key(model: SchemaModel, table: Table, column: str) -> ColumnReference | None:
    for fk in table.constraints_of("foreign_key"):
        if column not in fk.columns:
            continue
        written = fk.ref_table or ""
        schema, _, name = written.rpartition(".")
        target = resolve(model.tables, written) or ref_for("table", schema or None, name)
        at = fk.columns.index(column)
        return ColumnReference(table=target, column=_referenced_column(model, target, fk, at))
    return None


def _enum_values(model: SchemaModel, type_key: str | None) -> tuple[str, ...] | None:
    found = resolve(model.enum_types, type_key) if type_key else None
    return model.enum_types[found].values if found is not None else None


def column_facts(model: SchemaModel, table: ObjectRef | str, column: str) -> ColumnFacts:
    """What a writer supplying *column* of *table* must respect.

    *column* is the name as the parser folds it, or as the author wrote it. A
    foreign key's target is found the way :func:`resolve` finds a name, so a bare
    ``REFERENCES parent`` names the ``other.parent`` that ``search_path`` put
    there; a key that names no column references the target's primary key.

    Raises:
        KeyError: when *model* holds no such table, or the table no such column.
    """
    found = model.tables[table_ref(model, table)]
    col = _column(found, column)
    checks = tuple(
        c.expression
        for c in found.constraints_of("check")
        if c.expression and col.folded in expression_columns(c.expression)
    )
    return ColumnFacts(
        name=col.name,
        type_key=col.type_key,
        raw_sql_type=col.raw_sql_type,
        not_null=col.not_null,
        default=col.default,
        unique=_is_unique(found, col.folded),
        checks=checks,
        enum_values=_enum_values(model, col.type_key),
        foreign_key=_foreign_key(model, found, col.folded),
    )


def naming_hints(model: SchemaModel, table: ObjectRef | str) -> TableHints:
    """The surrogate-key / natural-id convention *table*'s names show.

    ``confiture introspect``'s own rule, over the model: the first primary-key
    column named ``pk_*``, and a column named ``id``. Heuristic signals, not facts
    — both ``None`` where the table shows neither.

    Raises:
        KeyError: when *model* holds no such table.
    """
    columns = model.tables[table_ref(model, table)].columns
    return TableHints.of([c.folded for c in columns if c.primary_key], {c.folded for c in columns})
