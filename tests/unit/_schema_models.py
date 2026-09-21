"""Schema models from a compact spec, for tests that compare or query one.

Drift compares a ``SchemaModel`` with a ``SchemaModel`` — the expected side built by
the lint inventory, the live side by ``live_catalog`` — and the SQL validator asks
a view of one. A test that wants to say "the database has lost this column" builds
the two models by hand, here, in the model's own types.

Usage::

    expected = model_of({"users": {"id": "integer", "email": {"type": "text", "nullable": False}}})
    actual = model(table("tenant.users", column("id", nullable=False)))
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from confiture.core.schema_model import Column, Constraint, Index, SchemaModel, Table, ref_for
from confiture.core.type_lattice import canonical_type


def column(
    name: str,
    type_text: str = "integer",
    *,
    nullable: bool = True,
    default: str | None = None,
    **facts: Any,
) -> Column:
    """One column; *facts* are any other :class:`Column` field (``identity``, …)."""
    return Column(
        name=name,
        folded=name,
        line=0,
        type_text=type_text,
        type_key=canonical_type(type_text),
        not_null=not nullable,
        default=default,
        **facts,
    )


def index(name: str | None, table: str, *columns: str, **facts: Any) -> Index:
    """One index on *table*; *facts* are ``unique``, ``method``, ``backs_constraint``…."""
    return Index(name=name, table=table, columns=columns, **facts)


def table(
    qualified: str,
    *columns: Column,
    constraints: Iterable[Constraint] = (),
    indexes: Iterable[Index | str] = (),
) -> Table:
    """A table named ``schema.name`` or ``name``; an index given by name has no keys."""
    schema, _, name = qualified.rpartition(".")
    return Table(
        name=name,
        schema=schema or None,
        columns=tuple(columns),
        constraints=tuple(constraints),
        indexes=tuple(
            ix if isinstance(ix, Index) else index(ix, qualified, method="btree") for ix in indexes
        ),
    )


def model(*tables: Table) -> SchemaModel:
    """The tables under the identity the readers key them by."""
    return SchemaModel(tables={ref_for("table", t.schema, t.name): t for t in tables})


def model_of(
    tables: Mapping[str, Mapping[str, str | Mapping[str, Any]]],
    *,
    indexes: Mapping[str, Iterable[Index | str]] | None = None,
    constraints: Mapping[str, Iterable[Constraint]] | None = None,
) -> SchemaModel:
    """``{"users": {"id": "integer", "email": {"type": "text", "nullable": False}}}``.

    A column is its type, or a mapping of ``type`` / ``nullable`` / ``default``.
    """

    def spelled(name: str, spec: str | Mapping[str, Any]) -> Column:
        if isinstance(spec, str):
            return column(name, spec)
        return column(
            name,
            spec.get("type", "integer"),
            nullable=spec.get("nullable", True),
            default=spec.get("default"),
        )

    return model(
        *(
            table(
                qualified,
                *(spelled(name, spec) for name, spec in columns.items()),
                constraints=(constraints or {}).get(qualified, ()),
                indexes=(indexes or {}).get(qualified, ()),
            )
            for qualified, columns in tables.items()
        )
    )
