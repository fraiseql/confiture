"""The column tracer agrees with PostgreSQL about where a plain column comes from.

libpq reports, for each column of a result, the table and column it is a plain
reference to (``PQftable``/``PQftablecol``, read here through psycopg's
``pgresult``), and ``0`` when it is anything else. Over a corpus of view queries
built into a throwaway database, ``core/linting/tenant/trace.py`` must give the same
answer, column by column: the same ``(schema, table, column)``, or no origin.

PostgreSQL and the tracer ask slightly different questions in three places, each a
named normalisation whose every use is counted — so a normalisation cannot quietly
absorb a real disagreement:

- ``set_operation``: PostgreSQL marks no origin on a ``UNION``'s columns; the tracer
  requires the column to trace in every branch. Each branch is run on its own and the
  union of its origins compared.
- ``through_view``: PostgreSQL names the view a column is read from (views are
  expanded after origins are marked); the tracer names the view's own origin. The
  view's answer is followed through that view's corpus entry, itself compared.
- ``recursive_cte``: PostgreSQL marks no origin through a recursive CTE; the tracer
  reads the column from the CTE's non-recursive term.

A column the tracer reports :class:`~confiture.core.linting.tenant.trace.Unread` is
outside the plain-column subset (``unread``), and is counted too.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

import pglast
import psycopg
from pglast.stream import RawStream

from confiture.config.project import TenancyConfig
from confiture.core.linting.inventory import build_inventory
from confiture.core.linting.tenant.scope import classify
from confiture.core.linting.tenant.trace import Origin, Unread
from confiture.core.linting.tenant.views import ViewScopes, view_definitions

_DDL = """
CREATE SCHEMA app;
CREATE SCHEMA catalog;
CREATE SCHEMA corpus;
CREATE TABLE app.tb_order (id int PRIMARY KEY, tenant_id int NOT NULL, total int);
CREATE TABLE app.tb_invoice (id int PRIMARY KEY, tenant_id int NOT NULL, fk_order int);
CREATE TABLE catalog.tb_format (id int PRIMARY KEY, label text);
"""

#: name → a view query. Each becomes ``corpus.<name>``, so one may read another.
CORPUS = {
    "plain": "SELECT o.tenant_id, o.id FROM app.tb_order o",
    "unaliased": "SELECT tb_order.tenant_id, total FROM app.tb_order",
    "star": "SELECT * FROM app.tb_order",
    "qualified_star": ("SELECT o.*, f.label FROM app.tb_order o CROSS JOIN catalog.tb_format f"),
    "cte": "WITH o AS (SELECT tenant_id, id FROM app.tb_order) SELECT o.tenant_id, o.id FROM o",
    "cte_columns": ("WITH o (a, b) AS (SELECT id, tenant_id FROM app.tb_order) SELECT a, b FROM o"),
    "subquery": "SELECT s.t FROM (SELECT tenant_id AS t, id FROM app.tb_order) s",
    "subquery_columns": "SELECT s.* FROM (SELECT id, tenant_id FROM app.tb_order) s (a, b)",
    "using": (
        "SELECT tenant_id, o.id, i.id AS invoice FROM app.tb_order o "
        "JOIN app.tb_invoice i USING (tenant_id)"
    ),
    "right_using": (
        "SELECT tenant_id FROM app.tb_order o RIGHT JOIN app.tb_invoice i USING (tenant_id)"
    ),
    "full_using": (
        "SELECT tenant_id FROM app.tb_order o FULL JOIN app.tb_invoice i USING (tenant_id)"
    ),
    "natural_star": (
        "SELECT * FROM (SELECT tenant_id, id FROM app.tb_order) o "
        "NATURAL JOIN (SELECT tenant_id, fk_order FROM app.tb_invoice) i"
    ),
    "join_alias": (
        "SELECT j.tenant_id, j.total FROM (app.tb_order JOIN app.tb_invoice USING (tenant_id)) j"
    ),
    "expressions": (
        "SELECT tenant_id::text AS t, coalesce(tenant_id, 0) AS c, total + 1 AS n, "
        "(SELECT max(id) FROM app.tb_invoice) AS m FROM app.tb_order"
    ),
    "aggregate": "SELECT tenant_id, count(*) AS n, max(total) FROM app.tb_order GROUP BY tenant_id",
    "union_all": (
        "SELECT tenant_id, id FROM app.tb_order UNION ALL SELECT tenant_id, id FROM app.tb_invoice"
    ),
    "union_literal": (
        "SELECT tenant_id, id FROM app.tb_order UNION SELECT NULL::int, id FROM app.tb_invoice"
    ),
    "through_view": "SELECT v.tenant_id, v.id FROM corpus.plain v",
    "recursive": (
        "WITH RECURSIVE t AS (SELECT tenant_id, id FROM app.tb_invoice WHERE fk_order IS NULL "
        "UNION ALL SELECT i.tenant_id, i.id FROM app.tb_invoice i JOIN t ON i.fk_order = t.id) "
        "SELECT t.tenant_id, t.id FROM t"
    ),
    "set_returning": "SELECT g, o.tenant_id FROM generate_series(1, 2) g, app.tb_order o",
}

#: How many columns each normalisation accounts for — measured, and pinned.
EXPECTED_NORMALISATIONS = {
    "set_operation": 4,
    "through_view": 2,
    "recursive_cte": 2,
    "unread": 1,
}

_Cell = frozenset[tuple[str, str, str]] | None


def _ddl() -> str:
    views = "".join(f"CREATE VIEW corpus.{name} AS {query};\n" for name, query in CORPUS.items())
    return _DDL + views


def _live(conn: psycopg.Connection, query: str) -> list[_Cell]:
    """PostgreSQL's origin of each column of *query*: ``{(schema, table, column)}`` or ``None``."""
    result: Any = conn.execute(query).pgresult
    cells: list[_Cell] = []
    for i in range(result.nfields):
        table, column = result.ftable(i), result.ftablecol(i)
        if table == 0:
            cells.append(None)
            continue
        row = conn.execute(
            "SELECT n.nspname, c.relname, a.attname FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE a.attrelid = %s AND a.attnum = %s",
            (table, column),
        ).fetchone()
        assert row is not None
        cells.append(frozenset({(row[0], row[1], row[2])}))
    return cells


class _Oracle:
    """PostgreSQL's answer for a corpus query, with each normalisation counted."""

    def __init__(self, conn: psycopg.Connection, traced: dict[str, list[Any]]) -> None:
        self.conn = conn
        self.traced = traced
        self.used: Counter[str] = Counter()

    def origins(self, stmt: Any) -> list[_Cell]:
        if stmt.larg is not None:
            left, right = self.origins(stmt.larg), self.origins(stmt.rarg)
            self.used["set_operation"] += len(left)
            return [
                None if a is None or b is None else a | b for a, b in zip(left, right, strict=True)
            ]
        return [self._through_views(cell) for cell in _live(self.conn, RawStream()(stmt))]

    def _through_views(self, cell: _Cell) -> _Cell:
        if cell is None or len(cell) != 1:
            return cell
        ((schema, name, column),) = cell
        if schema != "corpus":
            return cell
        self.used["through_view"] += 1
        source = next(o.source for o in self.traced[name] if o.name == column)
        return source.columns if isinstance(source, Origin) else None


def _traced(sql: str) -> dict[str, list[Any]]:
    inventory = build_inventory(sql)
    tables = classify(inventory.tables, TenancyConfig(), declarations={})
    scopes = ViewScopes(tables, inventory, view_definitions(None, sql), [])
    found: dict[str, list[Any]] = {}
    for name in CORPUS:
        columns = scopes.columns("corpus", name)
        assert not isinstance(columns, Unread), columns
        found[name] = list(columns)
    return found


def test_the_tracer_agrees_with_libpq_on_plain_columns(
    fresh_database_factory: Callable[[str], str],
) -> None:
    sql = _ddl()
    traced = _traced(sql)
    mismatches: list[str] = []
    with psycopg.connect(fresh_database_factory("tenant_trace"), autocommit=True) as conn:
        conn.execute(sql)
        oracle = _Oracle(conn, traced)
        for name, query in CORPUS.items():
            stmt = pglast.parse_sql(query)[0].stmt
            recursive = stmt.withClause is not None and stmt.withClause.recursive
            names = [f.name for f in conn.execute(query).description or ()]
            if [o.name for o in traced[name]] != names:
                mismatches.append(
                    f"{name}: tracer names {[o.name for o in traced[name]]}, libpq {names}"
                )
            for output, live in zip(traced[name], oracle.origins(stmt), strict=True):
                if isinstance(output.source, Unread):
                    oracle.used["unread"] += 1
                    continue
                mine = output.source.columns if isinstance(output.source, Origin) else None
                if recursive and live is None and mine is not None:
                    oracle.used["recursive_cte"] += 1
                    continue
                if mine != live:
                    mismatches.append(f"{name}.{output.name}: tracer {mine}, libpq {live}")

    assert mismatches == []
    assert dict(oracle.used) == EXPECTED_NORMALISATIONS
