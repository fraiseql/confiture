"""What preflight says about a migration that a pg_tviews TVIEW cannot survive (#504).

The backing view of a TVIEW depends on the columns of its base tables, so a
migration that drops or retypes one, or drops the table, fails unless it drops the
TVIEW first. :func:`live_issues` names each such change; it needs the TVIEWs a
database registers, which only a live database knows.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pglast
import pglast.parser
from pglast.stream import RawStream

from confiture.core._migrator.discovery import _version_from_migration_filename
from confiture.core.ddl_walk import column_edit, object_edits, tview_calls, walk_nodes
from confiture.core.linting.inventory import build_model
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import TVIEW_PREFIX
from confiture.core.sql_lexer import ParsedStatement, parse
from confiture.models.results import PreflightIssue


def live_issues(files: Iterable[Path], tviews: Mapping[str, str]) -> list[PreflightIssue]:
    """``PFLIGHT_TVIEW_BASE_COLUMN`` for each change to what a registered TVIEW reads.

    *tviews* maps ``schema.tv_name`` to the query pg_tviews recorded. A change is
    reported unless an earlier statement of the same file drops that TVIEW.
    """
    reads = {name: _Reads(query) for name, query in tviews.items()}
    issues: list[PreflightIssue] = []
    for path in files:
        version = _version_from_migration_filename(path.name)
        try:
            statements = parse(path.read_text(encoding="utf-8"))
        except (pglast.parser.ParseError, OSError):
            continue
        dropped: set[str] = set()
        for statement in statements:
            dropped |= _dropped_tviews(statement.stmt)
            issues.extend(
                _issue(version, path.name, statement, tview, table, column)
                for tview, table, column in _breaks(statement.stmt, reads)
                if tview not in dropped
            )
    return issues


def touches_tview(sql: str) -> bool:
    """Whether *sql* creates or drops a pg_tviews TVIEW; SQL the parser rejects touches none."""
    try:
        statements = parse(sql)
    except pglast.parser.ParseError:
        return False
    return any(
        _dropped_tviews(statement.stmt)
        or _creates_tview(statement.stmt)
        or tview_calls(statement.stmt)
        for statement in statements
    )


def _creates_tview(stmt: Any) -> bool:
    """``CREATE TABLE tv_* AS …``: the statement pg_tviews converts into a TVIEW."""
    into = getattr(stmt, "into", None)
    rel = getattr(into, "rel", None) if type(stmt).__name__ == "CreateTableAsStmt" else None
    return rel is not None and bool(build_model(RawStream()(stmt) + ";").tviews)


def _issue(
    version: str,
    file: str,
    statement: ParsedStatement,
    tview: str,
    table: str,
    column: str | None,
) -> PreflightIssue:
    what = f"drops table {table}" if column is None else f"changes column {table}.{column}"
    return PreflightIssue.of(
        "PFLIGHT_TVIEW_BASE_COLUMN",
        f"Migration {version} {what}, which the TVIEW {tview} reads: "
        "PostgreSQL refuses it while the TVIEW exists.",
        migration=version,
        file=file,
        line=statement.line,
        details={"tview": tview, "table": table, "column": column},
    )


def _dropped_tviews(stmt: Any) -> set[str]:
    """What *stmt* drops: ``DROP TABLE tv_*``, or ``tviews.pg_tviews_drop()``."""
    return {
        _key(edit.schema, edit.name)
        for edit in object_edits(stmt)
        if edit.kind == "drop" and edit.name.startswith(TVIEW_PREFIX)
    }


def _breaks(stmt: Any, reads: Mapping[str, _Reads]) -> Iterable[tuple[str, str, str | None]]:
    """``(tview, table, column)`` for each thing *stmt* takes from a TVIEW that reads it."""
    if type(stmt).__name__ == "AlterTableStmt":
        table = _key(stmt.relation.schemaname, stmt.relation.relname)
        for cmd in stmt.cmds or ():
            edit = column_edit(cmd)
            if edit is None or edit.kind not in {"drop", "retype"} or edit.column is None:
                continue
            for tview, read in reads.items():
                if read.column(table, edit.column):
                    yield tview, table, edit.column
        return
    for edit in object_edits(stmt):
        if edit.kind != "drop" or edit.object_kind != "table":
            continue
        table = _key(edit.schema, edit.name)
        for tview, read in reads.items():
            if table in read.tables:
                yield tview, table, None


def _key(schema: str | None, name: str) -> str:
    return f"{(schema or DEFAULT_SCHEMA).lower()}.{name.lower()}"


class _Reads:
    """The tables a TVIEW's query reads, and the columns it reads of them."""

    def __init__(self, query: str) -> None:
        self.tables: set[str] = set()
        self._aliases: dict[str, str] = {}
        self._qualified: set[tuple[str, str]] = set()
        self._bare: set[str] = set()
        self._star = False
        try:
            root = pglast.parse_sql(query)[0].stmt
        except (pglast.parser.ParseError, IndexError):
            self._star = True
            return
        nodes = list(walk_nodes(root))
        for node in nodes:
            if type(node).__name__ == "RangeVar":
                table = _key(node.schemaname, node.relname)
                self.tables.add(table)
                alias = getattr(getattr(node, "alias", None), "aliasname", None) or node.relname
                self._aliases[alias.lower()] = table
        for node in nodes:
            if type(node).__name__ != "ColumnRef":
                continue
            fields = [getattr(part, "sval", None) for part in node.fields]
            name = fields[-1]
            if name is None:
                self._star = True
            elif len(fields) == 1:
                self._bare.add(name.lower())
            else:
                table = self._aliases.get(str(fields[-2]).lower())
                if table is None:
                    self._bare.add(name.lower())
                else:
                    self._qualified.add((table, name.lower()))

    def column(self, table: str, column: str) -> bool:
        """Whether the query may read *column* of *table*: any doubt is a yes."""
        if table not in self.tables:
            return False
        name = column.lower()
        return self._star or name in self._bare or (table, name) in self._qualified
