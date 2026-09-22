"""What the model says about the objects in it, for a caller that writes into them.

The model (``core/schema_model.py``) is data; this module answers questions over
it. The first is which object a name refers to. DDL writes a reference as it
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

from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import ObjectRef, SchemaModel


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
