"""The views, matviews, triggers and routines a live database holds (issue #303).

A view, a materialized view, a trigger or a routine the DDL declares and the
database has not got was **exit 0** on the gate a deploy is failed by. `DriftType`
had no member for any of them, and the three body-drift checks do not cover it
either: they compare only the intersection of source and live keys, by design —
"Views present only on one side (added/removed) are outside this detector's
scope." So a dropped view was invisible in every check confiture had.

The expected side of that comparison already existed: ``core.ddl_objects``
(#288) reads what a DDL tree defines, including the kinds the lint inventory does
not model — a trigger among them. This module is the live half, keyed to match
the same ``ObjectRef``.

It is not part of the schema model yet: routines, views and triggers join it as
kinds of their own, and until then this is the live half of
:func:`confiture.core.drift.compare_objects` and reads **only** what that compares.
An extension is a good example of the temptation: ``ddl_objects`` tracks
``CREATE EXTENSION``, so the expected side is there for the taking, and the
comparison still does not exist. So this does not
read them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from confiture.core import live_catalog
from confiture.core.linting.inventory import signature_from_type_names

if TYPE_CHECKING:
    import psycopg

    from confiture.core.linting.inventory import Signature

#: ``relkind`` / ``prokind`` -> the kind vocabulary ``ddl_objects`` speaks.
_RELKINDS = {"v": "view", "m": "matview"}
_PROKINDS = {"f": "function", "p": "procedure", "a": "aggregate"}


@dataclass(frozen=True)
class LiveObject:
    """One object a live database holds, keyed the way a DDL tree keys it.

    ``name`` is the object's own name, except for a trigger — ``table.trigger``,
    because a trigger name is unique per *table*, not per schema, and two tables
    may each carry a ``trg_touch``. ``signature`` is a routine's input argument
    types canonicalised, which is what decides whether two routines are the same
    routine; ``None`` for every other kind.
    """

    kind: str
    schema: str
    name: str
    signature: Signature | None = None


@dataclass
class LiveObjects:
    """Every object of a compared kind, by kind."""

    objects: list[LiveObject] = field(default_factory=list)
    #: Kinds actually queried, so a comparison knows what silence means.
    kinds_read: frozenset[str] = frozenset()

    def of_kind(self, kind: str) -> list[LiveObject]:
        return [obj for obj in self.objects if obj.kind == kind]


class LiveObjectCatalog:
    """Read the objects a database holds, in the schemas a DDL tree declares.

    One ``core/live_catalog`` read per family, all filtered to the requested
    schemas — the schema names come from a user's DDL file, so they are
    parameters and never interpolated.

    Existence does not need a throwaway database. ``ExpectedSchemaDB`` exists for
    the body checks, which ask PostgreSQL about *resolved types*; asking it
    whether a view exists would make the cheapest check the heaviest.
    """

    #: The kinds this catalog reads, and therefore the kinds a comparison can
    #: report on. A kind absent here is not "none found", it is "not asked".
    KINDS = frozenset({"view", "matview", "trigger", "function", "procedure", "aggregate"})

    def __init__(self, connection: psycopg.Connection) -> None:
        self._conn = connection

    def read(self, schemas: list[str]) -> LiveObjects:
        """Every view, matview, trigger and routine in *schemas*.

        Objects PostgreSQL created as part of an extension are the extension's,
        not the DDL tree's: ``citext`` alone installs a dozen functions, so
        without leaving them out a pristine database reports dozens of extra
        routines.
        """
        wanted = sorted(set(schemas))
        found: list[LiveObject] = [
            *self._read_views(wanted),
            *self._read_triggers(wanted),
            *self._read_routines(wanted),
        ]
        return LiveObjects(objects=found, kinds_read=self.KINDS)

    def _read_views(self, wanted: list[str]) -> list[LiveObject]:
        return [
            LiveObject(kind=_RELKINDS[view.relkind], schema=view.schema, name=view.name)
            for view in live_catalog.views(self._conn, wanted)
            if view.relkind in _RELKINDS and not view.extension_owned
        ]

    def _read_triggers(self, wanted: list[str]) -> list[LiveObject]:
        return [
            LiveObject(
                kind="trigger", schema=trigger.schema, name=f"{trigger.table}.{trigger.name}"
            )
            for trigger in live_catalog.triggers(self._conn, wanted)
        ]

    def _read_routines(self, wanted: list[str]) -> list[LiveObject]:
        return [
            LiveObject(
                kind=_PROKINDS[routine.kind],
                schema=routine.schema,
                name=routine.name,
                signature=signature_from_type_names(routine.input_types),
            )
            for routine in live_catalog.routines(self._conn, wanted, kinds=tuple(_PROKINDS))
            if not routine.extension_owned
        ]
