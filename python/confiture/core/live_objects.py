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

It is deliberately *not* part of :class:`~confiture.core.schema_analyzer.SchemaInfo`:
that is ``SchemaAnalyzer``'s return type and is read by migration validation as
well, and four more dicts on a structure three other call sites walk would make
every one of them answer for objects it never asked about.

It reads **only** what :func:`confiture.core.drift.compare_objects` compares.
``SchemaInfo`` carried four fields — constraints, sequences, extensions, foreign
keys — queried on every run and compared by nothing, which is what published
three drift types confiture could not emit. An extension is a good example of the
temptation: ``ddl_objects`` tracks ``CREATE EXTENSION``, so the expected side is
there for the taking, and the comparison still does not exist. So this does not
read them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from confiture.core.linting.inventory import signature_from_type_names

if TYPE_CHECKING:
    import psycopg

    from confiture.core.linting.inventory import Signature

#: Objects PostgreSQL created as part of an extension are the extension's, not the
#: DDL tree's. ``citext`` alone installs a dozen functions, so without this a
#: pristine database reports dozens of extra routines.
_NOT_EXTENSION_OWNED = """
    AND NOT EXISTS (
        SELECT 1 FROM pg_depend d
        WHERE d.objid = {oid} AND d.classid = '{catalog}'::regclass AND d.deptype = 'e'
    )
"""

_VIEWS = f"""
SELECT n.nspname, c.relname, c.relkind
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('v', 'm')
  AND n.nspname = ANY(%s)
  {_NOT_EXTENSION_OWNED.format(oid="c.oid", catalog="pg_class")}
"""

# `NOT tgisinternal` is load-bearing: a FOREIGN KEY creates internal triggers on
# both tables, and reporting those would put two items on every FK in the schema.
_TRIGGERS = """
SELECT n.nspname, c.relname, t.tgname
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE NOT t.tgisinternal
  AND n.nspname = ANY(%s)
"""

# The input argument types, from `proargtypes` — *not*
# `pg_get_function_identity_arguments`, which on PostgreSQL 18 returns
# `a integer, OUT b integer` for a routine with an OUT parameter: parameter names
# and OUT parameters included, byte-identical to `pg_get_function_arguments`. The
# expected side counts neither, so every such routine would be permanently
# missing.
_ROUTINES = f"""
SELECT n.nspname, p.proname, p.prokind,
       (SELECT coalesce(array_agg(format_type(t, NULL) ORDER BY ord), '{{}}')
        FROM unnest(p.proargtypes) WITH ORDINALITY AS u(t, ord))
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = ANY(%s)
  AND p.prokind IN ('f', 'p', 'a')
  {_NOT_EXTENSION_OWNED.format(oid="p.oid", catalog="pg_proc")}
"""

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

    One query per family, all filtered to the requested schemas with ``= ANY(%s)``
    — the schema names come from a user's DDL file, so they are parameters and
    never interpolated.

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
        """Every view, matview, trigger and routine in *schemas*."""
        wanted = sorted(set(schemas))
        found: list[LiveObject] = [
            *self._read_views(wanted),
            *self._read_triggers(wanted),
            *self._read_routines(wanted),
        ]
        return LiveObjects(objects=found, kinds_read=self.KINDS)

    def _read_views(self, wanted: list[str]) -> list[LiveObject]:
        with self._conn.cursor() as cur:
            cur.execute(_VIEWS, (wanted,))
            return [
                LiveObject(kind=_RELKINDS[relkind], schema=schema, name=name)
                for schema, name, relkind in cur.fetchall()
                if relkind in _RELKINDS
            ]

    def _read_triggers(self, wanted: list[str]) -> list[LiveObject]:
        with self._conn.cursor() as cur:
            cur.execute(_TRIGGERS, (wanted,))
            return [
                LiveObject(kind="trigger", schema=schema, name=f"{table}.{trigger}")
                for schema, table, trigger in cur.fetchall()
            ]

    def _read_routines(self, wanted: list[str]) -> list[LiveObject]:
        with self._conn.cursor() as cur:
            cur.execute(_ROUTINES, (wanted,))
            return [
                LiveObject(
                    kind=_PROKINDS[prokind],
                    schema=schema,
                    name=name,
                    signature=signature_from_type_names(arg_types or ()),
                )
                for schema, name, prokind, arg_types in cur.fetchall()
                if prokind in _PROKINDS
            ]
