"""``tview_001`` … ``tview_004``: how a pg_tviews TVIEW's storage is left, read from the tree (#504).

pg_tviews turns ``CREATE TABLE tv_x AS SELECT …`` into a table it keeps in step with
its base tables, and what it leaves out is the tree's to say — through statements it
accepts after the conversion: ``CREATE INDEX``, ``ALTER TABLE … SET (fillfactor)`` and
``ALTER TABLE … SET LOGGED`` (measured; ``WITH (…)`` on the ``CREATE`` it refuses).
Each rule waits on a pg_tviews issue, named in its message, and is deleted with it.
What pg_tviews itself creates (the GIN on ``data``) is not in the DDL and is not read.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pglast
import pglast.parser

from confiture.core.ddl_walk import walk_nodes
from confiture.core.linting.inventory import distinct
from confiture.core.linting.tenant.trace import Unread, outputs
from confiture.core.schema_model import TVIEW_PREFIX

if TYPE_CHECKING:
    from confiture.core.linting.inventory import Inventory, SchemaObject
    from confiture.core.schema_model import Index

#: The columns every refresh rewrites: an index over one is never HOT.
_REWRITTEN = frozenset({"data", "updated_at"})

#: A fillfactor at or above this leaves pages full.
_FULL_PAGES = 100

#: ``(code, rule name, severity, object, message, fix, line)``.
Finding = tuple[str, str, str, str, str, str | None, int]


def tview_findings(inventory: Inventory, *, has_replicas: bool = False) -> Iterator[Finding]:
    """Every finding of the four rules over the TVIEWs *inventory* declares."""
    for tview in distinct(inventory.objects):
        if tview.kind != "tview":
            continue
        yield from _unindexed_keys(tview)
        yield from _hot_blockers(tview)
        yield from _full_pages(tview)
        if has_replicas:
            yield from _unlogged(tview)


def _unindexed_keys(tview: SchemaObject) -> Iterator[Finding]:
    pk = f"pk_{tview.name.removeprefix(TVIEW_PREFIX)}"
    leading = {_key_columns(index)[:1] for index in tview.indexes}
    for column in _output_names(tview):
        if column.startswith("fk_") and (column,) not in leading:
            yield (
                "tview_001",
                "TVIEW Foreign Key Unindexed",
                "warning",
                tview.qualified,
                f"TVIEW {tview.qualified}: {column} has no index leading with it, so every "
                "cascade step seq-scans the TVIEW (fraiseql/pg_tviews#71)",
                f"CREATE INDEX ON {tview.qualified} ({column}, {pk});",
                tview.line,
            )


def _hot_blockers(tview: SchemaObject) -> Iterator[Finding]:
    for index in tview.indexes:
        covered = sorted(_REWRITTEN.intersection(_referenced(index)))
        if covered:
            yield (
                "tview_002",
                "TVIEW Index Blocks HOT",
                "warning",
                tview.qualified,
                f"TVIEW {tview.qualified}: index {index.name or '(unnamed)'} covers "
                f"{', '.join(covered)}, which every refresh rewrites: no update is HOT "
                "(fraiseql/pg_tviews#70)",
                None,
                tview.index_lines.get(index, tview.line),
            )


def _full_pages(tview: SchemaObject) -> Iterator[Finding]:
    if tview.fillfactor is None or tview.fillfactor >= _FULL_PAGES:
        yield (
            "tview_003",
            "TVIEW Fillfactor 100",
            "info",
            tview.qualified,
            f"TVIEW {tview.qualified} keeps its pages full, so a refresh often cannot stay "
            "on its page and is not HOT (fraiseql/pg_tviews#73)",
            f"ALTER TABLE {tview.qualified} SET (fillfactor = 85);",
            tview.line,
        )


def _unlogged(tview: SchemaObject) -> Iterator[Finding]:
    if not tview.logged:
        yield (
            "tview_004",
            "TVIEW Unlogged With Replicas",
            "warning",
            tview.qualified,
            f"TVIEW {tview.qualified} is UNLOGGED (pg_tviews' default): a hot standby cannot "
            "read it and a promoted one holds it empty (fraiseql/pg_tviews#75)",
            f"ALTER TABLE {tview.qualified} SET LOGGED;",
            tview.line,
        )


class _NoRelations:
    """A TVIEW's names are the ones its ``SELECT`` writes: no relation's columns are needed."""

    def columns(self, schema: str | None, name: str) -> Unread:  # noqa: ARG002
        return Unread("names only")


def _output_names(tview: SchemaObject) -> list[str]:
    """The names the TVIEW's ``SELECT`` gives its columns; none it cannot read."""
    definition = tview.tview.definition if tview.tview is not None else None
    if not definition:
        return []
    try:
        select = pglast.parse_sql(definition)[0].stmt
    except (pglast.parser.ParseError, IndexError):
        return []
    return [column.name.lower() for column in outputs(select, _NoRelations()) if column.name]


def _key_columns(index: Index) -> tuple[str, ...]:
    return tuple(key.lower() for key in index.columns)


def _referenced(index: Index) -> set[str]:
    """Every column name any key of *index* reads, an expression's included."""
    found: set[str] = set()
    for key in index.columns:
        try:
            expression = pglast.parse_sql(f"SELECT {key}")[0].stmt
        except (pglast.parser.ParseError, IndexError):
            found.add(key.lower())
            continue
        for node in walk_nodes(expression):
            if type(node).__name__ == "ColumnRef":
                last = getattr(node.fields[-1], "sval", None)
                if last:
                    found.add(str(last).lower())
    return found
