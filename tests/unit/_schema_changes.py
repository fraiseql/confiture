"""Schema changes from a compact spec, for tests of what renders or reads one.

A renderer test used to build ``SchemaChange(type="ADD_COLUMN", new_value="TEXT NOT
NULL")`` — a string and a dict the differ may never have produced, so a test could
pass on an input nothing emits. A change is now a variant of ``core/schema_change``
carrying model objects, and these build them the way the differ does.

Usage::

    ColumnAdded("users", spelled("email", "TEXT", nullable=False))
    TableAdded(table("users", spelled("id", "SERIAL", nullable=False, primary_key=True)))
    added("view", "public.v", "CREATE OR REPLACE VIEW public.v AS SELECT 1")
"""

from __future__ import annotations

from typing import Any

from confiture.core.ddl_objects import DDLObject
from confiture.core.schema_change import ObjectReplaced
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import Column, ObjectRef
from tests.unit._schema_models import column


def spelled(
    name: str,
    type_sql: str = "INTEGER",
    *,
    nullable: bool = True,
    default: str | None = None,
    **facts: Any,
) -> Column:
    """A column whose generated DDL writes *type_sql* exactly as given."""
    return column(
        name, type_sql, nullable=nullable, default=default, raw_sql_type=type_sql, **facts
    )


def ref(kind: str, qualified: str, *, signature: tuple[str, ...] | None = None) -> ObjectRef:
    """The bucket of an object named ``schema.name`` or ``name``, spelled as given."""
    schema, _, name = qualified.rpartition(".")
    return ObjectRef(
        kind=kind,
        schema=(schema or DEFAULT_SCHEMA).lower(),
        name=name,
        signature=signature,
        display=qualified,
    )


def ddl_object(kind: str, qualified: str, create_sql: str, **ref_facts: Any) -> DDLObject:
    """One tracked ``CREATE``; its definition is the statement itself."""
    return DDLObject(
        ref=ref(kind, qualified, **ref_facts), definition=create_sql, create_sql=create_sql
    )


def replaced(
    kind: str, qualified: str, old_sql: str, new_sql: str, **ref_facts: Any
) -> ObjectReplaced:
    old = ddl_object(kind, qualified, old_sql, **ref_facts)
    new = ddl_object(kind, qualified, new_sql, **ref_facts)
    return ObjectReplaced(old.ref, old, new)
