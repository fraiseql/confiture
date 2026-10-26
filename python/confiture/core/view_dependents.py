"""The views a column change is refused under: what a migration drops and creates again (#765).

PostgreSQL refuses ``ALTER COLUMN … TYPE`` and ``DROP COLUMN`` on a column a view
reads (``cannot alter type of a column used by a view or rule``), and a view on
that view holds the first one in place. :func:`dependents` answers which views,
materialized views and TVIEWs those are, in the order they can be created — each
after the ones it reads — from one side's own statements, read by the one TVIEW
read graph (:mod:`confiture.core.linting.tview_reads`): a tree and a database are
answered alike, and nothing is asked of a live server.

A view is held by a column it names (``ReadGraph.reads_column``), and every view
reading a held one is held with it, whatever columns it reads.
"""

from collections.abc import Iterable, Mapping

from confiture.core.ddl_objects import DDLObject
from confiture.core.linting.inventory import DEFAULT_SCHEMA
from confiture.core.linting.tview_reads import Holder, ReadGraph, names_relation
from confiture.core.schema_model import ObjectRef
from confiture.core.schema_read import read_text

#: The kinds a column can be held by: each stores a query over its relations.
DEPENDENT_KINDS = frozenset({"view", "matview", "tview"})

#: A column a change cannot pass under while a view reads it: the table's
#: identity, ``(schema, name)``, and the column's folded name.
HeldColumn = tuple[tuple[str, str], str]


def dependents(
    objects: Mapping[ObjectRef, list[DDLObject]], held: Iterable[HeldColumn]
) -> list[ObjectRef]:
    """The views among *objects* that read a *held* column, directly or through one another.

    In dependency order: each after the views it reads.
    """
    held = list(held)
    read = _Read(objects)
    if not held or not read.holders:
        return []
    found = {
        identity
        for identity, holder in read.holders.items()
        if any(
            names_relation(written, table) and read.graph.reads_column(holder, table, column)
            for table, column in held
            for written in holder.relations
        )
    }
    while more := {
        identity
        for identity, holder in read.holders.items()
        if identity not in found
        and any(names_relation(w, f) for w in holder.relations for f in found)
    }:
        found |= more
    return read.ordered(found)


def in_dependency_order(
    objects: Mapping[ObjectRef, list[DDLObject]], refs: Iterable[ObjectRef]
) -> list[ObjectRef]:
    """*refs*, each after the ones among them it reads, as *objects* define them."""
    read = _Read(objects)
    return read.ordered({_ref_identity(ref) for ref in refs} & read.holders.keys())


def with_what_they_read(
    objects: Mapping[ObjectRef, list[DDLObject]],
    rebuilt: Iterable[ObjectRef],
    added: Iterable[ObjectRef],
) -> list[ObjectRef]:
    """*rebuilt*, and the *added* views they read, directly or through one another (#787).

    In dependency order, as *objects* define them: a view the rebuild creates again
    after the views a migration adds that it reads. An added view none of them
    reads is left out: it is created where a migration creates views.
    """
    read = _Read(objects)
    found = {_ref_identity(ref) for ref in rebuilt} & read.holders.keys()
    candidates = {_ref_identity(ref) for ref in added} & read.holders.keys()
    while more := {
        other
        for other in candidates - found
        if any(
            names_relation(written, other)
            for identity in found
            for written in read.holders[identity].relations
        )
    }:
        found |= more
    return read.ordered(found)


def _ref_identity(ref: ObjectRef) -> tuple[str, str]:
    return (ref.schema or DEFAULT_SCHEMA, ref.name)


class _Read:
    """One side's views, read once by the read graph, keyed by identity."""

    def __init__(self, objects: Mapping[ObjectRef, list[DDLObject]]) -> None:
        self.refs = {
            _ref_identity(ref): ref
            for ref in objects
            if ref.kind in DEPENDENT_KINDS and objects[ref]
        }
        self.holders: dict[tuple[str, str], Holder] = {}
        if not self.refs:
            return
        read = read_text("".join(f"{objects[r][-1].create_sql};\n" for r in self.refs.values()))
        self.graph = ReadGraph.read(read.files, read.inventory)
        for holder in self.graph.holders.values():
            identity = (holder.obj.folded_schema or DEFAULT_SCHEMA, holder.obj.folded_name)
            if identity in self.refs:
                self.holders[identity] = holder

    def ordered(self, found: set[tuple[str, str]]) -> list[ObjectRef]:
        """*found*, each after the members of *found* it reads; a cycle is broken where it closes."""
        ordered: list[tuple[str, str]] = []
        visiting: set[tuple[str, str]] = set()

        def visit(identity: tuple[str, str]) -> None:
            if identity in ordered or identity in visiting:
                return
            visiting.add(identity)
            for written in self.holders[identity].relations:
                for other in sorted(found):
                    if other != identity and names_relation(written, other):
                        visit(other)
            visiting.discard(identity)
            ordered.append(identity)

        for identity in self.holders:
            if identity in found:
                visit(identity)
        return [self.refs[identity] for identity in ordered]
