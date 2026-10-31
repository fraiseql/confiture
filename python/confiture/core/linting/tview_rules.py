"""``tview_001`` and ``tview_002``: how a pg_tviews TVIEW's storage is left, read from the tree (#504).

pg_tviews turns ``CREATE TABLE tv_x AS SELECT …`` into a table it keeps in step with
its base tables. From 0.1.0-beta.18 it indexes each ``fk_*`` column and sets
fillfactor 85 itself; what it leaves to the author is said on the ``CREATE``
(``UNLOGGED``, ``WITH (fillfactor = n)``), in a ``pg_tviews_create_or_replace()``
call's ``options``, or after the conversion (``CREATE INDEX``, ``ALTER TABLE … SET
LOGGED``). A TVIEW is LOGGED unless the tree says otherwise (pg_tviews' read contract
2); ``tview_002`` reads the ``logged`` the schema model pins, so the lint, drift and
generation agree on it. It waits on fraiseql/pg_tviews#75 and is deleted with it.
"""

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pglast
import pglast.parser

from confiture.core.ddl_walk import query_outputs, tview_query_tree, walk_nodes
from confiture.core.linting.inventory import distinct

if TYPE_CHECKING:
    from confiture.core.linting.inventory import Inventory, SchemaObject
    from confiture.core.schema_model import Index

#: The column every refresh rewrites: an index over it is never HOT.
_REWRITTEN = "data"

#: The row write time pg_tviews 0.1.0-beta.33 and earlier add to a TVIEW's table
#: and rewrite on every refresh. From 0.1.0-beta.34 the table holds only what the
#: definition outputs (#795), and a definition that projects its own ``updated_at``
#: (which failed before) holds the base row's: so it is pg_tviews' own, and
#: rewritten, exactly when the definition does not project it.
_STAMP = "updated_at"

#: ``(code, rule name, severity, object, message, fix, line)``.
Finding = tuple[str, str, str, str, str, str | None, str | None, int]


def tview_findings(inventory: Inventory, *, has_replicas: bool = False) -> Iterator[Finding]:
    """Every finding of the two rules over the TVIEWs *inventory* declares."""
    for tview in distinct(inventory.objects):
        if tview.kind != "tview":
            continue
        yield from _hot_blockers(tview)
        if has_replicas:
            yield from _unlogged(tview)


def _hot_blockers(tview: SchemaObject) -> Iterator[Finding]:
    rewritten = {_REWRITTEN} if _projects_stamp(tview) else {_REWRITTEN, _STAMP}
    for index in tview.indexes:
        covered = sorted(rewritten.intersection(_referenced(index)))
        if covered:
            stamp = (
                f". Its {_STAMP} is the one pg_tviews 0.1.0-beta.33 and earlier add; from "
                "0.1.0-beta.34 the table has none unless the definition projects it"
                if _STAMP in covered
                else ""
            )
            yield (
                "tview_001",
                "TVIEW Index Blocks HOT",
                "warning",
                tview.qualified,
                f"TVIEW {tview.qualified}: index {index.name or '(unnamed)'} covers "
                f"{', '.join(covered)}, which every refresh rewrites: no update is HOT{stamp}",
                None,
                *tview.index_sites.get(index, (tview.file, tview.line)),
            )


def _unlogged(tview: SchemaObject) -> Iterator[Finding]:
    if tview.tview is not None and tview.tview.logged is False:
        yield (
            "tview_002",
            "TVIEW Unlogged With Replicas",
            "warning",
            tview.qualified,
            f"TVIEW {tview.qualified} is UNLOGGED: a hot standby cannot read it and a "
            "promoted one holds it empty (fraiseql/pg_tviews#75)",
            f"ALTER TABLE {tview.qualified} SET LOGGED;",
            tview.file,
            tview.line,
        )


def _projects_stamp(tview: SchemaObject) -> bool:
    """Whether *tview*'s definition outputs an ``updated_at`` of its own.

    A definition whose outputs cannot all be named (a ``*``), or that does not
    parse, is read as not: the reading of pg_tviews 0.1.0-beta.33 and earlier, so
    the warning stands.
    """
    if tview.tview is None:
        return False
    try:
        outputs = query_outputs(tview_query_tree(tview.tview.definition))
    except pglast.parser.ParseError, IndexError:
        return False
    return _STAMP in (outputs or ())


def _referenced(index: Index) -> set[str]:
    """Every column name any key of *index* reads, an expression's included."""
    found: set[str] = set()
    for key in index.columns:
        try:
            expression = pglast.parse_sql(f"SELECT {key}")[0].stmt
        except pglast.parser.ParseError, IndexError:
            found.add(key.lower())
            continue
        for node in walk_nodes(expression):
            if type(node).__name__ == "ColumnRef":
                last = getattr(node.fields[-1], "sval", None)
                if last:
                    found.add(str(last).lower())
    return found
