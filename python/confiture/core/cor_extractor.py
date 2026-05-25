"""Extract CREATE OR REPLACE targets from pending migrations.

Walks SQL with :mod:`pglast` to find ``CREATE OR REPLACE VIEW`` and
``CREATE OR REPLACE FUNCTION`` / ``PROCEDURE`` nodes. Returns
:class:`~confiture.models.preflight.CorTarget` instances that the
:class:`~confiture.core.dependent_objects.DependentObjectsChecker`
resolves against the live preflight DB.

For ``.py`` migrations, :func:`find_cor_targets_in_file` routes through
the AST extractor in
:mod:`confiture.core.idempotency.python_migration_extractor` so inline
``self.execute(...)`` SQL is included.

This module requires ``pglast`` (the ``[ast]`` extra). It raises
:class:`ImportError` with a clean message at import time if pglast is
not installed.
"""

from __future__ import annotations

from pathlib import Path

try:
    from pglast import ast as pglast_ast
    from pglast import parse_sql
except ImportError as exc:  # pragma: no cover - import-time error
    raise ImportError(
        "Dependent check requires pglast. Install with: pip install fraiseql-confiture[ast]"
    ) from exc

from confiture.models.preflight import CorTarget


def _rangevar_to_qualified(rangevar: object) -> tuple[str, str]:
    """Extract (schema, name) from a pglast RangeVar."""
    schema = getattr(rangevar, "schemaname", None) or "public"
    name = getattr(rangevar, "relname", None) or ""
    return schema, name


def _funcname_to_qualified(funcname: tuple[object, ...] | None) -> tuple[str, str] | None:
    """Convert a pglast funcname tuple of String nodes to (schema, name)."""
    if not funcname:
        return None
    parts = [getattr(p, "sval", None) for p in funcname]
    parts = [p for p in parts if p]
    if not parts:
        return None
    if len(parts) == 1:
        return "public", parts[0]
    return parts[-2], parts[-1]


def find_cor_targets(
    sql: str,
    *,
    source_file: Path | None = None,
    source_line: int | None = None,
) -> list[CorTarget]:
    """Return CREATE OR REPLACE targets in the given SQL.

    Walks the pglast AST for ``ViewStmt`` and ``CreateFunctionStmt`` nodes
    where ``replace=True``. Materialized views are skipped — PostgreSQL
    rejects ``CREATE OR REPLACE MATERIALIZED VIEW``; the idempotency
    regex detector in
    :mod:`confiture.core.idempotency.patterns` handles the rare cases
    where the syntax appears in source SQL.
    """
    try:
        parsed = parse_sql(sql)
    except Exception:  # pragma: no cover - pglast raises on bad SQL
        return []

    targets: list[CorTarget] = []
    for raw in parsed:
        stmt = raw.stmt
        if isinstance(stmt, pglast_ast.ViewStmt):
            if not getattr(stmt, "replace", False):
                continue
            schema, name = _rangevar_to_qualified(stmt.view)
            targets.append(
                CorTarget(
                    kind="view",
                    schema=schema,
                    name=name,
                    source_file=source_file,
                    source_line=source_line,
                )
            )
        elif isinstance(stmt, pglast_ast.CreateFunctionStmt):
            if not getattr(stmt, "replace", False):
                continue
            resolved = _funcname_to_qualified(stmt.funcname)
            if resolved is None:
                continue
            schema, name = resolved
            kind = "procedure" if getattr(stmt, "is_procedure", False) else "function"
            targets.append(
                CorTarget(
                    kind=kind,
                    schema=schema,
                    name=name,
                    source_file=source_file,
                    source_line=source_line,
                )
            )
    return targets


def find_cor_targets_in_file(
    path: Path,
    *,
    project_root: Path | None = None,
) -> list[CorTarget]:
    """Find CoR targets in a migration file (``.sql`` or ``.py``).

    For ``.py`` files, this routes through the stdlib-AST extractor in
    :mod:`confiture.core.idempotency.python_migration_extractor` so each
    inline ``self.execute(...)`` snippet is parsed individually and its
    source line is attached to the resulting target. For ``.sql`` files,
    the file is parsed as a single SQL string.
    """
    if path.suffix == ".py":
        from confiture.core.idempotency.python_migration_extractor import (
            extract_sql_from_python_migration,
        )

        extraction = extract_sql_from_python_migration(path, project_root=project_root)
        targets: list[CorTarget] = []
        for snippet in extraction.snippets:
            targets.extend(
                find_cor_targets(
                    snippet.sql,
                    source_file=path,
                    source_line=snippet.source_line,
                )
            )
        return targets

    sql = path.read_text(encoding="utf-8")
    return find_cor_targets(sql, source_file=path, source_line=None)
