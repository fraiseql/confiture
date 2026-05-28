"""Lint rule ``func_001`` for function/procedure uniqueness (issue #136).

``confiture build`` concatenates every ``.sql`` file in the configured
DDL directories.  PostgreSQL then keeps the *last-loaded* definition of
any function or procedure that appears in more than one file; the
earlier copies are silently overwritten at build time.  ``func_001``
catches the duplicate before it ships.

Mirrors :mod:`confiture.core.linting.libraries.ownership` on the
function-uniqueness axis: AST-only via pglast, emits a single skip
notice when pglast is unavailable, opt-in via the
``function_coverage:`` env block.

Kind-aware key
==============
The duplicate-detection key is ``(kind, schema, name,
param_types_tuple)`` where ``kind`` ∈ ``{"function", "procedure"}``.
PostgreSQL keeps functions and procedures in separate namespaces, so
``CREATE FUNCTION foo()`` and ``CREATE PROCEDURE foo()`` do not
collide.  Overloads (different argument types) are likewise distinct.

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
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from confiture.config.environment import FunctionCoverage
from confiture.core.idempotency._ast_visitor import _first_keyword_pos
from confiture.core.linting._ast_required import (
    emit_skip_notice,
    is_pglast_available,
)
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity

# Default schema for unqualified callable names.
_DEFAULT_SCHEMA = "public"

# Directive: opt the *next* CREATE FUNCTION/PROCEDURE out of duplicate
# detection.  Lives on its own ``-- confiture:func-allow-duplicate`` line;
# trailing characters are tolerated so a follow-on comment still matches.
_FUNC_ALLOW_DUPLICATE_RE = re.compile(r"--\s*confiture:func-allow-duplicate\b", re.IGNORECASE)

# Parameter modes that do NOT participate in overload resolution.  Per
# PostgreSQL docs: only IN, INOUT, and VARIADIC are signature-significant.
# DEFAULT is treated as IN by the parser.  TABLE-return columns appear
# with mode FUNC_PARAM_TABLE and are likewise non-signature.
_NON_SIGNATURE_MODES: frozenset[str] = frozenset({"FUNC_PARAM_OUT", "FUNC_PARAM_TABLE"})

# Common pg_catalog type aliases.  pglast canonicalizes user-written
# ``integer`` to ``pg_catalog.int4``; we map it back so the key matches
# regardless of which alias the author used.  Equality of the key is the
# only thing that matters — these names also surface in violation
# messages so we keep the human form.
_PG_CATALOG_ALIASES: dict[str, str] = {
    "int2": "smallint",
    "int4": "integer",
    "int8": "bigint",
    "float4": "real",
    "float8": "double precision",
    "bool": "boolean",
    "varchar": "varchar",
    "bpchar": "char",
    "timestamp": "timestamp",
    "timestamptz": "timestamp with time zone",
    "timetz": "time with time zone",
}


@dataclass(frozen=True)
class _CallableDefinition:
    """One ``CREATE FUNCTION``/``CREATE PROCEDURE`` statement found by the AST walk."""

    kind: str  # "function" or "procedure"
    schema: str
    name: str
    param_types: tuple[str, ...]
    file: Path
    line: int

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}"

    @property
    def signature_key(self) -> tuple[str, str, str, tuple[str, ...]]:
        return (self.kind, self.schema, self.name, self.param_types)

    @property
    def display_signature(self) -> str:
        params = ", ".join(self.param_types) if self.param_types else ""
        return f"{self.qualified_name}({params})"


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
        if not is_pglast_available():
            emit_skip_notice(
                'func_001 requires the [ast] extra: pip install "fraiseql-confiture[ast]"'
            )
            return []

        all_definitions: list[_CallableDefinition] = []
        for path in ddl_paths:
            for sql_file in self._iter_sql_files(path):
                all_definitions.extend(
                    self._extract_callable_signatures(sql_file.read_text(), sql_file)
                )

        if not all_definitions:
            return []

        # Group by signature key, drop the unique ones, emit one
        # violation per duplicate cluster.
        clusters: dict[tuple[str, str, str, tuple[str, ...]], list[_CallableDefinition]] = (
            defaultdict(list)
        )
        for defn in all_definitions:
            if not self._in_scope(defn):
                continue
            clusters[defn.signature_key].append(defn)

        violations: list[LintViolation] = []
        for key, defs in clusters.items():
            if len(defs) < 2:
                continue
            kind = key[0]
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
        return sorted(path.rglob("*.sql"))

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
        import pglast  # local import — guarded by is_pglast_available()

        try:
            tree = pglast.parse_sql(sql)
        except Exception:
            return []

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
            definitions.append(
                _CallableDefinition(
                    kind=kind,
                    schema=schema,
                    name=name,
                    param_types=param_types,
                    file=file_path,
                    line=line,
                )
            )
        return definitions

    @staticmethod
    def _split_funcname(funcname: object) -> tuple[str, str]:
        """Return ``(schema, name)`` from pglast's funcname node list."""
        parts = [n.sval for n in funcname]  # type: ignore[attr-defined]
        if len(parts) == 1:
            return _DEFAULT_SCHEMA, parts[0]
        # Per PostgreSQL: db.schema.name allowed only in CREATE; treat
        # the last two segments as schema.name and ignore any leading
        # database name (defensive — confiture never emits a 3-part name).
        return parts[-2], parts[-1]

    @staticmethod
    def _extract_param_types(parameters: object) -> tuple[str, ...]:
        """Return signature-significant parameter types, normalized."""
        if not parameters:
            return ()
        types: list[str] = []
        for p in parameters:  # type: ignore[union-attr]
            mode = p.mode
            mode_name = mode.name if mode else ""
            if mode_name in _NON_SIGNATURE_MODES:
                continue
            type_name = Func001FunctionUniqueness._render_typename(p.argType)
            types.append(type_name)
        return tuple(types)

    @staticmethod
    def _render_typename(type_node: object) -> str:
        """Render a pglast ``TypeName`` node into a normalized string."""
        names = [n.sval for n in type_node.names]  # type: ignore[attr-defined]
        if len(names) == 2 and names[0] == "pg_catalog":
            base = _PG_CATALOG_ALIASES.get(names[1], names[1])
        else:
            base = ".".join(names)
        # Append array bounds if present (e.g. integer[])
        bounds = getattr(type_node, "arrayBounds", None)
        if bounds:
            base = f"{base}{'[]' * len(bounds)}"
        return base

    # ------------------------------------------------------------------ #
    # Directives                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _collect_allow_duplicate_lines(text: str) -> set[int]:
        """Return 1-indexed line numbers of CREATE statements opted out.

        ``-- confiture:func-allow-duplicate`` attaches to the *next*
        non-blank non-comment line within the file.  This walker returns
        the line numbers of those attached lines so the AST walk can
        match against ``defn.line``.
        """
        skipped: set[int] = set()
        pending_skip = False
        for idx, raw in enumerate(text.splitlines(), start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("--"):
                if _FUNC_ALLOW_DUPLICATE_RE.search(stripped):
                    pending_skip = True
                continue
            if pending_skip:
                skipped.add(idx)
                pending_skip = False
        return skipped


__all__ = ["Func001FunctionUniqueness"]
