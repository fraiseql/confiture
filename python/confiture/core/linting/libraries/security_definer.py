"""Lint rule ``sec_002`` — SECURITY DEFINER functions must pin search_path.

A ``SECURITY DEFINER`` function (or procedure) that does not pin
``search_path`` resolves unqualified object names through the *caller's*
``search_path``.  This is the classic privilege-escalation vector
(CVE-2018-1058): an attacker places a shadow object in a schema earlier
in the caller's path.

**Definition of "pinned"** (consistent between static and live paths):
a ``SET search_path = …`` or ``SET search_path FROM CURRENT`` clause.
``RESET search_path`` and ``SET search_path TO DEFAULT`` do *not* pin —
they leave the function exposed to the caller's path.

Static path (this module): parses the DDL source with pglast and reports
per-file/line violations with full object names.  pglast is a dependency
, so there is no absent-parser path: a file it rejects is a finding,
not a skip.

Live path: see :mod:`confiture.core.validation.security_definer`
 which queries ``pg_proc.proconfig`` directly.

Opt-out directive
=================
Place ``-- confiture:secdef-allow-unpinned`` on the line immediately
above a ``CREATE FUNCTION`` / ``CREATE PROCEDURE`` to suppress that
specific function from detection (for deliberate, reviewed exceptions).

Known limitation
================
If a function is defined without ``SET search_path`` but later patched
by ``ALTER FUNCTION … SET search_path`` in a separate file, the static
scan will false-positive.  The live catalog path (``proconfig``) is
authoritative for this case and will correctly report it as pinned.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import pglast
import pglast.parser

from confiture.core import live_catalog, sql_lexer
from confiture.core.builder import files_under
from confiture.core.idempotency._ast_visitor import _first_keyword_pos
from confiture.core.linting.inventory import type_text
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity
from confiture.core.linting.unparseable import unparseable_notice

_DEFAULT_SCHEMA = "public"
_SYSTEM_SCHEMAS: frozenset[str] = frozenset({"pg_catalog", "information_schema"})

#: Every ``prokind``: the live check asks about any routine that can be SECURITY DEFINER.
_EVERY_PROKIND = ("f", "p", "a", "w")

# Directive: opt the *next* CREATE FUNCTION/PROCEDURE out of sec_002.
_SECDEF_ALLOW = "secdef-allow-unpinned"

# pglast VariableSetKind integer values.
# VAR_SET_VALUE(0): SET search_path = a, b
# VAR_SET_DEFAULT(1): SET search_path TO DEFAULT — does NOT pin
# VAR_SET_CURRENT(2): SET search_path FROM CURRENT — pins
# VAR_SET_MULTI(3): SET LOCAL — not relevant here
# VAR_RESET(4): RESET search_path — does NOT pin
_PINNING_KINDS: frozenset[int] = frozenset({0, 2})


@dataclass(frozen=True)
class _FunctionDefRecord:
    """One ``CREATE FUNCTION``/``CREATE PROCEDURE`` statement found by the AST walk."""

    schema: str
    name: str
    is_security_definer: bool
    search_path_pinned: bool
    line: int
    file: Path

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}"


def _is_security_definer(stmt: Any) -> bool:
    """Return True when *stmt* has a ``SECURITY DEFINER`` clause."""
    options = stmt.options
    if not options:
        return False
    for opt in options:
        if opt.defname == "security":
            arg = opt.arg
            # pglast Boolean node: boolval attribute holds a Python bool.
            return bool(getattr(arg, "boolval", False))
    return False


def _search_path_pinned(stmt: Any) -> bool:
    """Return True when *stmt* pins search_path via SET … or FROM CURRENT."""
    options = stmt.options
    if not options:
        return False
    for opt in options:
        if opt.defname != "set":
            continue
        arg = opt.arg
        if not arg:
            continue
        if getattr(arg, "name", None) != "search_path":
            continue
        kind_node = getattr(arg, "kind", None)
        if kind_node is None:
            continue
        # pglast exposes enums as Python ints (the underlying IntEnum value).
        kind_int = int(kind_node)
        if kind_int in _PINNING_KINDS:
            return True
    return False


def _split_funcname(funcname: Any) -> tuple[str, str]:
    """Return ``(schema, name)`` from pglast's funcname node list."""
    parts = [n.sval for n in funcname]
    if len(parts) == 1:
        return _DEFAULT_SCHEMA, parts[0]
    return parts[-2], parts[-1]


_NON_SIGNATURE_MODES: frozenset[str] = frozenset({"FUNC_PARAM_OUT", "FUNC_PARAM_TABLE"})


def _render_param_list(parameters: Any) -> str:
    """A comma-separated arg-type string for an ``ALTER FUNCTION`` signature.

    `inventory.type_text` — the types **as written** — and deliberately not the
    canonical key `func_001` compares on. This string goes into the
    ``ALTER FUNCTION app.f(…) SET search_path`` statement the finding tells the
    operator to run, so it should read the way their `CREATE` reads. Both read
    the inventory; neither keeps an alias table of its own (#275).
    """
    if not parameters:
        return ""
    return ", ".join(
        type_text(p.argType)
        for p in parameters
        if (p.mode.name if p.mode else "") not in _NON_SIGNATURE_MODES
    )


def _make_alter_sql(schema: str, name: str, param_list: str) -> str:
    """Return the ALTER FUNCTION … SET search_path fix statement."""
    sig = f"{schema}.{name}({param_list})"
    return f"ALTER FUNCTION {sig} SET search_path = pg_catalog, public;"


def _collect_allow_unpinned_lines(text: str) -> set[int]:
    """Return 1-indexed line numbers of statements opted out via directive.

    The directive attaches to the statement below it
    (:func:`confiture.core.sql_lexer.directives`).
    """
    return {
        d.statement_line
        for d in sql_lexer.directives(text)
        if d.name == _SECDEF_ALLOW and d.statement_line is not None
    }


class Sec002SecurityDefinerSearchPath:
    """SEC002 — SECURITY DEFINER functions/procedures must pin search_path.

    Returns one :class:`~confiture.core.linting.schema_linter.LintViolation`
    per flagged function.

    Args:
        apply_to: Schema-name patterns (``fnmatch``-style) that scope the
            check.  ``["*"]`` covers every schema.
        ignore: Object-path globs (``schema.name``) that opt specific
            callables out of detection.
        severity: Violation severity emitted.  Defaults to
            :attr:`~confiture.core.linting.schema_linter.RuleSeverity.WARNING`
            so the rule is advisory by default; set to
            :attr:`~confiture.core.linting.schema_linter.RuleSeverity.ERROR`
            to make it a hard CI gate.

    Example::

        from pathlib import Path
        from confiture.core.linting.libraries.security_definer import (
            Sec002SecurityDefinerSearchPath,
        )
        from confiture.core.linting.schema_linter import RuleSeverity

        rule = Sec002SecurityDefinerSearchPath(severity=RuleSeverity.ERROR)
        violations = rule.check([Path("db/schema")])
        for v in violations:
            print(v.message)
    """

    rule_id: ClassVar[str] = "sec_002"
    rule_name: ClassVar[str] = "Security Definer Search Path"

    def __init__(
        self,
        *,
        apply_to: list[str] | None = None,
        ignore: list[str] | None = None,
        severity: RuleSeverity = RuleSeverity.WARNING,
    ) -> None:
        self.apply_to: list[str] = apply_to if apply_to is not None else ["*"]
        self.ignore: list[str] = ignore or []
        self.severity = severity

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def check(self, scan_paths: list[Path]) -> list[LintViolation]:
        """Walk *scan_paths* and return one violation per flagged function.

        Each path may be a directory (scanned recursively for ``*.sql``)
        or a single file.  Missing paths are silently ignored.
        """
        violations: list[LintViolation] = []
        for path in scan_paths:
            for sql_file in self._iter_sql_files(path):
                text = sql_file.read_text()
                try:
                    violations.extend(self._extract_violations(text, sql_file))
                except pglast.parser.ParseError as exc:
                    violations.append(unparseable_notice(sql_file, text, exc))
        return violations

    # ------------------------------------------------------------------ #
    # File walking                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _iter_sql_files(path: Path) -> list[Path]:
        if not path.exists():
            return []
        if path.is_file():
            return [path] if path.suffix == ".sql" else []
        return files_under(path)

    # ------------------------------------------------------------------ #
    # Scope filtering                                                     #
    # ------------------------------------------------------------------ #

    def _in_scope(self, record: _FunctionDefRecord) -> bool:
        if record.schema in _SYSTEM_SCHEMAS:
            return False
        if not any(fnmatch.fnmatchcase(record.schema, pat) for pat in self.apply_to):
            return False
        return not any(fnmatch.fnmatchcase(record.qualified_name, pat) for pat in self.ignore)

    # ------------------------------------------------------------------ #
    # AST extraction                                                      #
    # ------------------------------------------------------------------ #

    def _extract_violations(self, sql: str, file_path: Path) -> list[LintViolation]:

        tree = pglast.parse_sql(sql)  # ParseError propagates: check() reports the file

        allow_lines = _collect_allow_unpinned_lines(sql)
        violations: list[LintViolation] = []

        for raw in tree or []:
            stmt = raw.stmt
            if stmt is None or type(stmt).__name__ != "CreateFunctionStmt":
                continue

            stmt_location = raw.stmt_location or 0
            keyword_pos = _first_keyword_pos(sql, stmt_location)
            line = sql[:keyword_pos].count("\n") + 1
            if line in allow_lines:
                continue

            # getattr, not attribute access: the CreateFunctionStmt narrowing
            # above is a runtime `type(...).__name__` check ty cannot follow, and
            # pglast 8's stubs type `raw.stmt` as a bare `Node` union. This is the
            # same accessor pattern the other AST walkers use (#192).
            schema, name = _split_funcname(getattr(stmt, "funcname", ()))
            record = _FunctionDefRecord(
                schema=schema,
                name=name,
                is_security_definer=_is_security_definer(stmt),
                search_path_pinned=_search_path_pinned(stmt),
                line=line,
                file=file_path,
            )

            if not record.is_security_definer:
                continue
            if record.search_path_pinned:
                continue
            if not self._in_scope(record):
                continue

            kind = "procedure" if getattr(stmt, "is_procedure", False) else "function"
            param_list = _render_param_list(getattr(stmt, "parameters", None))
            fix_sql = _make_alter_sql(record.schema, record.name, param_list)
            violations.append(
                LintViolation(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    severity=self.severity,
                    object_type=kind,
                    object_name=record.qualified_name,
                    message=(
                        f"{kind.capitalize()} '{record.qualified_name}' is "
                        f"SECURITY DEFINER but does not pin search_path. "
                        f"An attacker can shadow objects via the caller's "
                        f"search_path (CVE-2018-1058). Fix: add "
                        f"`SET search_path = pg_catalog, public` (or `= ''`) "
                        f"to the function definition, or add "
                        f"`-- confiture:secdef-allow-unpinned` above the "
                        f"CREATE statement for deliberate exceptions."
                    ),
                    file_path=str(file_path),
                    line_number=line,
                    suggested_fix=fix_sql,
                )
            )
        return violations

    # ------------------------------------------------------------------ #
    # Live catalog path                                                   #
    # ------------------------------------------------------------------ #

    def check_live(
        self,
        conn: Any,
        *,
        schemas: list[str],
        exclude_extensions: bool = True,
    ) -> list[LintViolation]:
        """Return violations for the live database's unpinned SECURITY DEFINER callables.

        This is the authoritative path for migrate-strategy databases where
        ``ALTER FUNCTION … SET search_path`` may have pinned a function after the
        original ``CREATE``, so the static DDL scan can't see the ALTER.

        Args:
            conn: An open ``psycopg.Connection`` (autocommit or within a transaction).
            schemas: Database schema names to scan.  System schemas
                (``pg_catalog``, ``information_schema``) are always excluded.
            exclude_extensions: When ``True`` (default), skip functions owned by
                PostgreSQL extensions (filtered via ``pg_depend`` with
                ``deptype = 'e'``).  Set to ``False`` to include them.

        Returns:
            List of :class:`~confiture.core.linting.schema_linter.LintViolation`,
            one per unpinned SECURITY DEFINER function/procedure.
        """
        unpinned = [
            routine
            for routine in live_catalog.routines(conn, schemas, kinds=_EVERY_PROKIND)
            if routine.security_definer
            and not routine.search_path_pinned
            and not (exclude_extensions and routine.extension_owned)
        ]

        violations: list[LintViolation] = []
        for routine in unpinned:
            schema = routine.schema
            name = routine.name
            kind = "procedure" if routine.kind == "p" else "function"
            qualified = f"{schema}.{name}"
            identity_args = routine.identity_arguments

            if schema in _SYSTEM_SCHEMAS:
                continue
            if not any(fnmatch.fnmatchcase(schema, pat) for pat in self.apply_to):
                continue
            if any(fnmatch.fnmatchcase(qualified, pat) for pat in self.ignore):
                continue

            fix_sql = _make_alter_sql(schema, name, identity_args)
            violations.append(
                LintViolation(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    severity=self.severity,
                    object_type=kind,
                    object_name=qualified,
                    message=(
                        f"{kind.capitalize()} '{qualified}' is "
                        f"SECURITY DEFINER but does not pin search_path. "
                        f"An attacker can shadow objects via the caller's "
                        f"search_path (CVE-2018-1058). Fix: "
                        f"`ALTER FUNCTION {qualified} SET search_path = pg_catalog, public;`"
                        f", or use `SET search_path = ''` for maximum isolation."
                    ),
                    file_path=None,
                    line_number=None,
                    suggested_fix=fix_sql,
                )
            )
        return violations


__all__ = ["Sec002SecurityDefinerSearchPath"]
