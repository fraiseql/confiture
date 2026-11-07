"""What a view outputs and what it reads, answered from the model alone (#812).

A view, a materialized view and a pg_tviews TVIEW are held in the model as their
name and their query's text (``View.definition``, ``TView.definition``): the DDL's
``SELECT`` rendered, or what the database holds. Two questions a tool asks of them are
answered here, the same for a model read from DDL and one read from a database.

- :func:`view_columns`: the names of the columns it outputs, in order. They are
  the column tracer's (:mod:`~confiture.core.linting.tenant.trace`), which expands
  ``*`` and ``t.*`` through ``FROM`` — joins (``USING`` and ``NATURAL`` columns
  first), subqueries, CTEs, ``VALUES``, a set operation's first branch — and each
  relation the model holds: a table's columns, or another view's outputs, asked
  again. An expression nobody named is named as PostgreSQL names it
  (:func:`~confiture.core.ddl_walk.figure_colname`), ``?column?`` included. A view's
  column list is part of its definition (the tree writes it there as
  ``pg_get_viewdef`` does). A ``*`` over what the model cannot expand — a relation
  it does not hold, a set-returning function — is refused, never guessed.
- :func:`view_reads`: every relation it reads, directly or through the views,
  materialized views and TVIEWs it reads, each as the model's reference. A
  relation's reads are the read graph's (:mod:`~confiture.core.linting.tview_reads`):
  every relation its query names, at any depth, a CTE's name excluded. A routine's
  body is not followed — a TVIEW declares the tables its functions read
  (``TView.function_reads``), and those are read. A relation the model does not
  hold (an extension's, a schema not read) is returned all the same, as a bare
  reference of kind ``relation``, never dropped.

A definition PostgreSQL's parser rejects, or a view with none, is refused with a
:class:`~confiture.exceptions.SchemaError` naming it.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from confiture.core.ddl_clauses import relation
from confiture.core.linting.tenant.trace import Output, Unread, outputs
from confiture.core.linting.tview_reads import Holder, ReadGraph
from confiture.core.model_facts import NotInModelError, read_name, resolve
from confiture.core.schema_model import ObjectRef, RelationName, SchemaModel, ref_for
from confiture.core.schema_read import Segment, read_segments
from confiture.exceptions import SchemaError

#: The kinds :func:`view_columns` and :func:`view_reads` answer for.
VIEW_KINDS = frozenset({"view", "matview", "tview"})

#: The kind of a reference to a relation the model does not hold.
UNKNOWN_RELATION = "relation"

_CREATE = {"view": "VIEW", "matview": "MATERIALIZED VIEW", "tview": "TABLE"}


def view_columns(model: SchemaModel, view: ObjectRef | str) -> tuple[str, ...]:
    """The names of the columns *view* outputs, in order.

    *view* is a view, a materialized view or a TVIEW: a reference the model holds,
    or a name resolved as DDL's is (``schema.name``, or a bare name the default
    schema holds or exactly one schema does).

    Raises:
        NotInModelError: when *model* holds no such view.
        SchemaError: when its definition does not parse, or a ``*`` in it reads
            what the model cannot expand.
    """
    views = _Views(model)
    return views.columns(views.ref(view))


def view_reads(model: SchemaModel, view: ObjectRef | str) -> frozenset[ObjectRef]:
    """The relations *view* reads, directly or through the views it reads.

    Tables, views, materialized views and TVIEWs, each the model's reference; one
    the model does not hold as a reference of kind ``relation``.

    Raises:
        NotInModelError: when *model* holds no such view.
        SchemaError: when a definition on the way does not parse.
    """
    views = _Views(model)
    start = views.ref(view)
    found: set[ObjectRef] = set()
    pending = [start]
    while pending:
        for read in views.reads(pending.pop()):
            if read not in found:
                found.add(read)
                if read.kind in VIEW_KINDS:
                    pending.append(read)
    return frozenset(found)


@dataclass
class _Views:
    """A model's views, each read once when first asked about."""

    model: SchemaModel
    holders: dict[ObjectRef, Holder] = field(default_factory=dict)
    named: dict[ObjectRef, tuple[str, ...] | Unread] = field(default_factory=dict)

    def ref(self, view: ObjectRef | str) -> ObjectRef:
        held = [*self.model.views, *self.model.tviews]
        found = view if isinstance(view, ObjectRef) else resolve(held, view)
        if found is None or found not in held:
            raise NotInModelError(
                f"no view, materialized view or TVIEW {view!r} in the model",
                resolution_hint=(
                    "Name one the model holds: schema.name, or a bare name the default "
                    "schema holds or exactly one schema does"
                ),
            )
        return found

    def definition(self, ref: ObjectRef) -> str | None:
        held = self.model.tviews[ref] if ref.kind == "tview" else self.model.views[ref]
        return held.definition

    def holder(self, ref: ObjectRef) -> Holder:
        """*ref*'s query, read by the read graph: rendered as the statement that creates it."""
        if ref in self.holders:
            return self.holders[ref]
        definition = (self.definition(ref) or "").strip().removesuffix(";")
        if not definition:
            raise SchemaError(f"{ref.kind} {ref.display} has no definition in the model")
        name = relation(RelationName(ref.schema, ref.name))
        text = f"CREATE {_CREATE[ref.kind]} {name} AS {definition}"
        try:
            read = read_segments([Segment(None, text, label=ref.display)])
        except SchemaError as error:
            raise SchemaError(
                f"{ref.kind} {ref.display}'s definition does not parse: {error.message}",
                context={"view": ref.display},
            ) from error
        graph = ReadGraph.read(read.files, read.inventory)
        holder = next((h for h in graph.holders.values() if h.obj.kind == ref.kind), None)
        if holder is None or not holder.queries:
            raise SchemaError(f"{ref.kind} {ref.display}'s definition holds no query")
        self.holders[ref] = holder
        return holder

    def relation_ref(self, written: RelationName | str) -> ObjectRef | None:
        model = self.model
        return resolve([*model.tables, *model.views, *model.tviews, *model.sequences], written)

    def reads(self, ref: ObjectRef) -> list[ObjectRef]:
        """What *ref*'s own definition reads: each relation it names, and a TVIEW's ``function_reads``."""
        written: list[RelationName | str] = [
            RelationName(schema, name) for schema, name in self.holder(ref).relations
        ]
        if ref.kind == "tview":
            reads = self.model.tviews[ref].function_reads or ()
            written += [table for read in reads for table in read.tables]
        return [self.relation_ref(name) or _unknown(name) for name in written]

    def columns(self, ref: ObjectRef) -> tuple[str, ...]:
        named = self._named(ref)
        if isinstance(named, Unread):
            raise SchemaError(
                f"{ref.kind} {ref.display}'s columns cannot be named: {named.reason}",
                context={"view": ref.display},
                resolution_hint=(
                    "Name the columns where the query reads what the model does not hold: "
                    "list them instead of *, or read the relation into the model too"
                ),
            )
        return named

    def _named(self, ref: ObjectRef) -> tuple[str, ...] | Unread:
        if ref not in self.named:
            # Asked again before it is answered: the view reads itself.
            self.named[ref] = Unread(f"{ref.display} reads itself")
            found = outputs(self.holder(ref).queries[0].root, _Relations(self))
            unread = next((c for c in found if c.name is None), None)
            if unread is None:
                self.named[ref] = tuple(c.name for c in found if c.name is not None)
            else:
                source = unread.source
                self.named[ref] = (
                    source if isinstance(source, Unread) else Unread("an output has no name")
                )
        return self.named[ref]


@dataclass(frozen=True)
class _Relations:
    """What a relation in a view's ``FROM`` outputs: a table's columns, a view's outputs."""

    views: _Views

    def columns(self, schema: str | None, name: str) -> Sequence[Output] | Unread:
        written = RelationName(schema, name)
        ref = self.views.relation_ref(written)
        if ref is None:
            return Unread(f"{relation(written)} is not in the model")
        if ref.kind == "table":
            return [Output(column.name, None) for column in self.views.model.tables[ref].columns]
        if ref.kind not in VIEW_KINDS:
            return Unread(f"{ref.display} is a {ref.kind}")
        try:
            named = self.views._named(ref)
        except SchemaError as error:
            return Unread(error.message)
        if isinstance(named, Unread):
            return named
        return [Output(column, None) for column in named]


def _unknown(written: RelationName | str) -> ObjectRef:
    """A relation the model does not hold, as a bare reference: its schema the default's when unwritten."""
    name = written if isinstance(written, RelationName) else read_name(written)
    if name is None:
        return ref_for(UNKNOWN_RELATION, None, str(written))
    return ref_for(UNKNOWN_RELATION, name.schema, name.name)
