"""Lint rule ``func_001`` for function/procedure uniqueness (issue #136).

``confiture build`` concatenates every ``.sql`` file in the configured
DDL directories.  PostgreSQL then keeps the *last-loaded* definition of
any function or procedure that appears in more than one file; the
earlier copies are silently overwritten at build time.  ``func_001``
catches the duplicate before it ships.

Mirrors :mod:`confiture.core.linting.libraries.ownership` on the
function-uniqueness axis: AST-only via pglast, opt-in via the
``function_coverage:`` env block.

Kind-aware key
==============
The duplicate-detection key is ``(kind, schema, name,
param_type_names)`` where ``kind`` ∈ ``{"function", "procedure"}`` and the
types are canonical — ``int8`` and ``bigint`` are one signature.
PostgreSQL keeps functions and procedures in separate namespaces, so
``CREATE FUNCTION foo()`` and ``CREATE PROCEDURE foo()`` do not
collide.  Overloads (different argument types) are likewise distinct.

It is a bucket rather than the whole answer, and
:func:`~confiture.core.linting.inventory.group_by_signature` gives the rest:
a type schema written on one definition and left off the other still names
one type, so ``app.f(app.custom_t)`` and ``app.f(custom_t)`` are a duplicate
while ``app.f(other.custom_t)`` is a third signature.  That is the
inventory's rule, read from the inventory — ``doc_002``, ``build_001`` and
this rule agree by construction rather than by coincidence.

OUT parameters do not participate in PostgreSQL's overload resolution,
so they are excluded from the key — two definitions that differ only in
their OUT params are still duplicates.

Opt-out directive
=================
A ``-- confiture:func-allow-duplicate`` line immediately above a
``CREATE FUNCTION`` / ``CREATE PROCEDURE`` excludes that statement from
the duplicate-detection map (mirrors ``-- confiture:owner-skip``).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import pglast
import pglast.parser

from confiture.config.environment import FunctionCoverage
from confiture.core import sql_lexer
from confiture.core.builder import files_under
from confiture.core.idempotency._ast_visitor import _first_keyword_pos
from confiture.core.linting.inventory import (
    Signature,
    group_by_signature,
    signature_bucket,
    type_key,
    type_text,
)
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity
from confiture.core.linting.unparseable import unparseable_notice

# Default schema for unqualified callable names.
_DEFAULT_SCHEMA = "public"

# Directive: opt the *next* CREATE FUNCTION/PROCEDURE out of duplicate
# detection.  Lives on its own ``-- confiture:func-allow-duplicate`` line;
# trailing characters are tolerated so a follow-on comment still matches.
_FUNC_ALLOW_DUPLICATE = "func-allow-duplicate"

# Parameter modes that do NOT participate in overload resolution.  Per
# PostgreSQL docs: only IN, INOUT, and VARIADIC are signature-significant.
# DEFAULT is treated as IN by the parser.  TABLE-return columns appear
# with mode FUNC_PARAM_TABLE and are likewise non-signature.
_NON_SIGNATURE_MODES: frozenset[str] = frozenset({"FUNC_PARAM_OUT", "FUNC_PARAM_TABLE"})


@dataclass(frozen=True)
class _CallableDefinition:
    """One ``CREATE FUNCTION``/``CREATE PROCEDURE`` statement found by the AST walk."""

    kind: str  # "function" or "procedure"
    schema: str
    name: str
    #: The canonical argument types — what decides whether two definitions are
    #: the same signature. `int8` and `bigint` are one entry here and two in
    #: `param_text` (#275).
    param_types: Signature
    #: The same arguments as the author wrote them, for the message.
    param_text: tuple[str, ...]
    file: Path
    line: int

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}"

    @property
    def bucket_key(self) -> tuple[str, str, str, tuple[str, ...] | None]:
        """What could be the same signature; :func:`group_by_signature` says what is.

        The argument types' own schemas are left out, so a bare spelling and a
        qualified one share a bucket — a dict key cannot express "a missing
        schema matches any schema". Same shape, same reason, as
        :func:`~confiture.core.linting.inventory.object_key`.
        """
        return (self.kind, self.schema, self.name, signature_bucket(self.param_types))

    @property
    def display_signature(self) -> str:
        return f"{self.qualified_name}({', '.join(self.param_text)})"


class Func001FunctionUniqueness:
    """FUNC001 — every function/procedure signature must be defined exactly once.

    The rule is a no-op when ``coverage.enabled`` is False, when no
    coverage block is provided, or when pglast is unavailable.

    Args:
        coverage: Parsed ``function_coverage:`` block from the
            environment config.

    Example::

        from pathlib import Path
        from confiture.config.environment import Environment
        from confiture.core.linting.libraries.functions import (
            Func001FunctionUniqueness,
        )

        env = Environment.load("local")
        if env.function_coverage is not None:
            rule = Func001FunctionUniqueness(coverage=env.function_coverage)
            for v in rule.check([Path("db/schema")]):
                print(v)
    """

    rule_id: ClassVar[str] = "func_001"
    rule_name: ClassVar[str] = "Function Uniqueness"

    def __init__(self, coverage: FunctionCoverage) -> None:
        self.coverage = coverage

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def check(self, ddl_paths: list[Path]) -> list[LintViolation]:
        """Walk *ddl_paths* and return one violation per duplicate signature.

        Each path may be a directory (scanned recursively for ``*.sql``)
        or a single file.  Missing paths are silently ignored — the
        rule's contract is "no findings when there's nothing to scan."
        """
        if not self.coverage.enabled:
            return []
        all_definitions: list[_CallableDefinition] = []
        notices: list[LintViolation] = []
        for path in ddl_paths:
            for sql_file in self._iter_sql_files(path):
                text = sql_file.read_text()
                try:
                    all_definitions.extend(self._extract_callable_signatures(text, sql_file))
                except pglast.parser.ParseError as exc:
                    notices.append(unparseable_notice(sql_file, text, exc))
        if not all_definitions:
            return notices

        # Group by signature, drop the unique ones, emit one violation per
        # duplicate cluster.
        clusters = group_by_signature(
            [defn for defn in all_definitions if self._in_scope(defn)],
            lambda defn: defn.bucket_key,
            lambda defn: defn.param_types,
        )

        violations: list[LintViolation] = list(notices)
        for defs in clusters:
            if len(defs) < 2:
                continue
            kind = defs[0].kind
            display = defs[0].display_signature
            files = ", ".join(str(d.file.name) for d in defs)
            violations.append(
                LintViolation(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    severity=RuleSeverity.ERROR,
                    object_type=kind,
                    object_name=defs[0].qualified_name,
                    message=(
                        f"{kind.capitalize()} '{display}' is defined in "
                        f"{len(defs)} files: {files}. `confiture build` will "
                        f"silently keep whichever copy is loaded last; the "
                        f"earlier definitions are dropped. Resolve by "
                        f"removing the duplicate or marking one with "
                        f"`-- confiture:func-allow-duplicate`."
                    ),
                    file_path=str(defs[0].file),
                    line_number=defs[0].line,
                )
            )
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

    def _in_scope(self, defn: _CallableDefinition) -> bool:
        # apply_to schema-name patterns
        if not any(fnmatch.fnmatchcase(defn.schema, pat) for pat in self.coverage.apply_to):
            return False
        # ignore object-path globs
        return not any(
            fnmatch.fnmatchcase(defn.qualified_name, pat) for pat in self.coverage.ignore
        )

    # ------------------------------------------------------------------ #
    # AST extraction                                                      #
    # ------------------------------------------------------------------ #

    def _extract_callable_signatures(self, sql: str, file_path: Path) -> list[_CallableDefinition]:
        """Parse *sql* and return its CREATE FUNCTION/PROCEDURE statements.

        Statements wrapped in ``DO $$ … $$`` blocks are opaque to pglast
        and never appear here — by design.  Templated SQL that fails to
        parse yields no definitions (the build-time gate would catch
        unparseable SQL separately).
        """

        tree = pglast.parse_sql(sql)  # ParseError propagates: check() reports the file

        skip_lines = self._collect_allow_duplicate_lines(sql)
        definitions: list[_CallableDefinition] = []

        for raw in tree or []:
            stmt = raw.stmt
            if type(stmt).__name__ != "CreateFunctionStmt":
                continue

            stmt_location = raw.stmt_location or 0
            keyword_pos = _first_keyword_pos(sql, stmt_location)
            line = sql[:keyword_pos].count("\n") + 1
            if line in skip_lines:
                continue

            kind = "procedure" if stmt.is_procedure else "function"
            schema, name = self._split_funcname(stmt.funcname)
            param_types = self._extract_param_types(stmt.parameters)
            param_text = self._extract_param_text(stmt.parameters)
            definitions.append(
                _CallableDefinition(
                    kind=kind,
                    schema=schema,
                    name=name,
                    param_types=param_types,
                    param_text=param_text,
                    file=file_path,
                    line=line,
                )
            )
        return definitions

    @staticmethod
    def _split_funcname(funcname: Any) -> tuple[str, str]:
        """Return ``(schema, name)`` from pglast's funcname node list."""
        parts = [n.sval for n in funcname]
        if len(parts) == 1:
            return _DEFAULT_SCHEMA, parts[0]
        # Per PostgreSQL: db.schema.name allowed only in CREATE; treat
        # the last two segments as schema.name and ignore any leading
        # database name (defensive — confiture never emits a 3-part name).
        return parts[-2], parts[-1]

    @staticmethod
    def _signature_parameters(parameters: Any) -> list[Any]:
        """The parameters that take part in overload resolution."""
        return [
            p
            for p in parameters or []
            if (p.mode.name if p.mode else "") not in _NON_SIGNATURE_MODES
        ]

    @staticmethod
    def _extract_param_types(parameters: Any) -> tuple[tuple[str | None, str], ...]:
        """The canonical argument types: the identity two definitions are compared on.

        `inventory.type_key`, not a table of this module's own: every alias the
        canonicaliser knows — `int8` and `bigint` as much as `int` and `integer`
        — must make two definitions one signature, or `func_001` misses a
        duplicate PostgreSQL rejects (#275).
        """
        return tuple(
            type_key(p.argType) for p in Func001FunctionUniqueness._signature_parameters(parameters)
        )

    @staticmethod
    def _extract_param_text(parameters: Any) -> tuple[str, ...]:
        """The same arguments as written, for the message the operator reads."""
        return tuple(
            type_text(p.argType)
            for p in Func001FunctionUniqueness._signature_parameters(parameters)
        )

    # ------------------------------------------------------------------ #
    # Directives                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _collect_allow_duplicate_lines(text: str) -> set[int]:
        """Return 1-indexed line numbers of CREATE statements opted out.

        ``-- confiture:func-allow-duplicate`` attaches to the statement
        below it (:func:`confiture.core.sql_lexer.directives`); the AST walk
        matches these lines against ``defn.line``.
        """
        return {
            d.statement_line
            for d in sql_lexer.directives(text)
            if d.name == _FUNC_ALLOW_DUPLICATE and d.statement_line is not None
        }


__all__ = ["Func001FunctionUniqueness"]
