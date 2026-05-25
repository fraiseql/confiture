"""Live dependent-objects checker for ``migrate preflight``.

Given a list of CREATE OR REPLACE targets extracted from pending
migrations, runs ``pg_depend`` queries against a live preflight DB and
returns the live objects (views, matviews, functions) that depend on
each target. Surfaces the transitive-breakage case that the static CoR
shape-risk heuristic in
:mod:`confiture.core.idempotency.patterns` cannot reach.
"""

from __future__ import annotations

from typing import Any

from confiture.models.preflight import (
    CorTarget,
    DependentAnalysisReport,
    DependentEntry,
    DependentObject,
)

# Map the user-facing "kind" string to the pg_class.relkind chars we look up.
# Views and matviews live in pg_class; functions/procedures live in pg_proc.
_RELKIND_FOR_KIND: dict[str, tuple[str, ...]] = {
    "view": ("v",),
    "matview": ("m",),
}

# Returns one row per dependent object. Joins pg_depend through pg_rewrite
# (for views / matviews referencing the target's columns) and through
# pg_class for the dependent object itself. Aggregates referenced columns
# from the target side via the attnum -> attname lookup.
_REL_DEPENDENTS_SQL = """
WITH target AS (
  SELECT c.oid AS target_oid, c.relkind AS target_kind
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = %(schema)s
    AND c.relname  = %(name)s
    AND c.relkind  = ANY(%(kinds)s::"char"[])
)
SELECT
  d_class.relkind         AS dependent_relkind,
  d_ns.nspname            AS dependent_schema,
  d_class.relname         AS dependent_name,
  COALESCE(
    array_agg(DISTINCT a.attname ORDER BY a.attname)
      FILTER (WHERE a.attname IS NOT NULL),
    '{}'::text[]
  )                       AS referenced_columns
FROM target t
JOIN pg_depend dep   ON dep.refobjid = t.target_oid
JOIN pg_rewrite rw   ON rw.oid = dep.objid
JOIN pg_class d_class ON d_class.oid = rw.ev_class AND d_class.oid <> t.target_oid
JOIN pg_namespace d_ns ON d_ns.oid = d_class.relnamespace
LEFT JOIN pg_attribute a
       ON a.attrelid = t.target_oid AND a.attnum = dep.refobjsubid AND a.attnum > 0
GROUP BY d_class.relkind, d_ns.nspname, d_class.relname;
"""

# Function/procedure dependents: pg_depend referring to a pg_proc OID
# captures rules and other functions/views that reference the function.
_PROC_DEPENDENTS_SQL = """
WITH target AS (
  SELECT p.oid AS target_oid
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname = %(schema)s
    AND p.proname = %(name)s
)
SELECT DISTINCT
  d_class.relkind         AS dependent_relkind,
  d_ns.nspname            AS dependent_schema,
  d_class.relname         AS dependent_name,
  '{}'::text[]            AS referenced_columns
FROM target t
JOIN pg_depend dep   ON dep.refobjid = t.target_oid
                     AND dep.refclassid = 'pg_proc'::regclass
JOIN pg_rewrite rw   ON rw.oid = dep.objid
JOIN pg_class d_class ON d_class.oid = rw.ev_class
JOIN pg_namespace d_ns ON d_ns.oid = d_class.relnamespace;
"""


_RELKIND_TO_KIND = {
    "v": "view",
    "m": "matview",
    "r": "table",
    "f": "foreign_table",
    "p": "partitioned_table",
}


class DependentObjectsChecker:
    """Enumerate live dependents of a set of CREATE OR REPLACE targets."""

    def __init__(self, severity: str = "error") -> None:
        """Build a checker.

        Args:
            severity: ``"error"`` (default) or ``"info"``. When ``"info"``,
                entries with dependents are still rendered but
                :meth:`DependentAnalysisReport.has_blocking` returns False.
        """
        if severity not in {"error", "info"}:
            raise ValueError(f"severity must be 'error' or 'info', got {severity!r}")
        self._severity = severity

    def check(
        self,
        targets: list[CorTarget],
        connection: Any,
    ) -> DependentAnalysisReport:
        """Resolve each target against ``connection`` and return a report.

        Args:
            targets: CREATE OR REPLACE targets extracted from pending migrations.
            connection: An open psycopg3 connection to the preflight DB.

        Returns:
            :class:`DependentAnalysisReport` with one entry per target.
        """
        entries: list[DependentEntry] = []
        for target in targets:
            dependents = self._resolve_one(target, connection)
            entries.append(
                DependentEntry(
                    target=target,
                    dependents=dependents,
                    severity=self._severity,
                )
            )
        return DependentAnalysisReport(entries=entries, status="ok")

    def _resolve_one(self, target: CorTarget, connection: Any) -> list[DependentObject]:
        """Run the right pg_depend query for ``target.kind``."""
        if target.kind in {"view", "matview"}:
            kinds = _RELKIND_FOR_KIND[target.kind]
            params = {"schema": target.schema, "name": target.name, "kinds": list(kinds)}
            sql = _REL_DEPENDENTS_SQL
        elif target.kind in {"function", "procedure"}:
            params = {"schema": target.schema, "name": target.name}
            sql = _PROC_DEPENDENTS_SQL
        else:
            return []

        with connection.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        dependents: list[DependentObject] = []
        for row in rows:
            relkind, schema, name, cols = row
            dependents.append(
                DependentObject(
                    kind=_RELKIND_TO_KIND.get(relkind, "object"),
                    schema=schema,
                    name=name,
                    referenced_columns=tuple(cols or ()),
                )
            )
        return dependents
