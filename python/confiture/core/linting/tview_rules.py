"""``tview_001`` and ``tview_002``: how a pg_tviews TVIEW's storage is left, read from the tree (#504).

pg_tviews turns ``CREATE TABLE tv_x AS SELECT …`` into a table it keeps in step with
its base tables. From 0.1.0-beta.18 it indexes each ``fk_*`` column and sets
fillfactor 85 itself; what it leaves to the author is said on the ``CREATE``
(``UNLOGGED``, ``WITH (fillfactor = n)``), in a ``pg_tviews_create_or_replace()``
call's ``options``, or after the conversion (``CREATE INDEX``, ``ALTER TABLE … SET
LOGGED``). ``tview_002`` reads the ``logged`` the schema model pins, so the lint,
drift and generation agree on it. It waits on fraiseql/pg_tviews#75 and is deleted
with it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pglast
import pglast.parser

from confiture.core.ddl_walk import walk_nodes
from confiture.core.linting.inventory import distinct

if TYPE_CHECKING:
    from confiture.core.linting.inventory import Inventory, SchemaObject
    from confiture.core.schema_model import Index

#: The columns every refresh rewrites: an index over one is never HOT.
_REWRITTEN = frozenset({"data", "updated_at"})

#: ``(code, rule name, severity, object, message, fix, line)``.
Finding = tuple[str, str, str, str, str, str | None, int]


def tview_findings(inventory: Inventory, *, has_replicas: bool = False) -> Iterator[Finding]:
    """Every finding of the two rules over the TVIEWs *inventory* declares."""
    for tview in distinct(inventory.objects):
        if tview.kind != "tview":
            continue
        yield from _hot_blockers(tview)
        if has_replicas:
            yield from _unlogged(tview)


def _hot_blockers(tview: SchemaObject) -> Iterator[Finding]:
    for index in tview.indexes:
        covered = sorted(_REWRITTEN.intersection(_referenced(index)))
        if covered:
            yield (
                "tview_001",
                "TVIEW Index Blocks HOT",
                "warning",
                tview.qualified,
                f"TVIEW {tview.qualified}: index {index.name or '(unnamed)'} covers "
                f"{', '.join(covered)}, which every refresh rewrites: no update is HOT",
                None,
                tview.index_lines.get(index, tview.line),
            )


def _unlogged(tview: SchemaObject) -> Iterator[Finding]:
    if tview.tview is None or tview.tview.logged is not True:
        yield (
            "tview_002",
            "TVIEW Unlogged With Replicas",
            "warning",
            tview.qualified,
            f"TVIEW {tview.qualified} is UNLOGGED (pg_tviews' default): a hot standby cannot "
            "read it and a promoted one holds it empty (fraiseql/pg_tviews#75)",
            f"ALTER TABLE {tview.qualified} SET LOGGED;",
            tview.line,
        )


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
