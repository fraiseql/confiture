"""Lint rule for ownership coverage of migration files (OWN001, issue #124).

``own_001`` fires when a migration file ``CREATE``s a relation in scope
of the configured ``ownership:`` block but does not pair it with a
matching ``ALTER … OWNER TO <expected_owner>`` later in the same file.

Mirrors :mod:`confiture.core.linting.libraries.acl` (issue #120) on the
ownership axis.

AST-only by design — pairwise ``CREATE`` ↔ ``ALTER … OWNER TO``
matching across realistic PostgreSQL SQL (dollar-quoted strings,
CHECK-constraint literals, multi-statement DO blocks) is too brittle to
ship as a regex.  When pglast is not installed the rule emits a single
skip notice and returns no violations rather than risk a false-negative
green check.

Trust boundary: ``-- confiture:run-as <role>`` is **declarative only**.
The lint rule trusts the comment; nothing at lint time verifies the
migration actually runs as that role in production.  The runtime drift
detector (:class:`~confiture.core.drift.OwnershipDriftDetector`) is the
production-time gate.  The two are designed to be complementary —
neither alone is sufficient.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from confiture.config.environment import OwnershipExpectation
from confiture.core.idempotency._ast_visitor import _first_keyword_pos
from confiture.core.linting._ast_required import (
    emit_skip_notice,
    is_pglast_available,
)
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity

# Default schema for unqualified identifiers in PostgreSQL.
_DEFAULT_SCHEMA = "public"

# Directive: opt the *next* CREATE statement out of the rule.  Lives on
# its own ``-- confiture:owner-skip`` line; trailing characters are
# tolerated so a follow-on comment still matches.
_OWNER_SKIP_RE = re.compile(r"--\s*confiture:owner-skip\b", re.IGNORECASE)
# Front-matter directive: declares the role the whole file is applied as.
# When the declared role equals ``expected_owner`` the file is skipped
# entirely.
_RUN_AS_RE = re.compile(r"--\s*confiture:run-as\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE)

# Maps the relkind characters declared on ``OwnershipApplyTo`` to the
# pglast statement classes that introduce each relkind.  Used purely for
# scope filtering at violation time — the AST walk itself looks at every
# create stmt and decides scope per-relation.
_RELKIND_TO_CREATE_LABEL: dict[str, str] = {
    "r": "table",
    "v": "view",
    "m": "materialized view",
    "S": "sequence",
}


@dataclass(frozen=True)
class _CreateRecord:
    """One ``CREATE`` statement found by the AST walk."""

    schema: str
    relname: str
    relkind: str  # one of "r", "v", "m", "S"
    line: int


@dataclass(frozen=True)
class _AlterOwnerRecord:
    """One ``ALTER … OWNER TO <role>`` statement found by the AST walk."""

    schema: str
    relname: str
    new_owner: str


class Own001OwnershipCoverage:
    """OWN001 — every created relation must have a matching ALTER OWNER.

    The rule is a no-op when ``expectation.lint_enabled`` is False, when
    no expectation is provided, or when pglast is unavailable.

    Args:
        expectation: Parsed ``ownership:`` block from the environment config.

    Example::

        from pathlib import Path
        from confiture.config.environment import Environment
        from confiture.core.linting.libraries.ownership import (
            Own001OwnershipCoverage,
        )

        env = Environment.load("local")
        if env.ownership is not None:
            rule = Own001OwnershipCoverage(expectation=env.ownership)
            for v in rule.check(Path("db/migrations")):
                print(v)
    """

    rule_id: ClassVar[str] = "own_001"
    rule_name: ClassVar[str] = "Ownership Coverage"

    def __init__(self, expectation: OwnershipExpectation) -> None:
        self.expectation = expectation
        # Pre-compute schema → set(relkinds) lookup for fast scope checks.
        self._scope: dict[str, set[str]] = {}
        for entry in expectation.apply_to:
            self._scope.setdefault(entry.schema_, set()).update(entry.relkinds)

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def check(self, migrations_dir: Path) -> list[LintViolation]:
        """Walk *migrations_dir* and return one violation per uncovered relation."""
        if not self.expectation.lint_enabled:
            return []
        if not migrations_dir.exists():
            return []
        if not is_pglast_available():
            emit_skip_notice(
                'own_001 requires the [ast] extra: pip install "fraiseql-confiture[ast]"'
            )
            return []

        violations: list[LintViolation] = []
        for migration in sorted(migrations_dir.rglob("*.up.sql")):
            violations.extend(self._check_file(migration))
        return violations

    # ------------------------------------------------------------------ #
    # Per-file analysis                                                   #
    # ------------------------------------------------------------------ #

    def _check_file(self, path: Path) -> list[LintViolation]:
        text = path.read_text()

        # Front-matter ``-- confiture:run-as <role>`` short-circuit.
        run_as = self._extract_run_as(text)
        if run_as == self.expectation.expected_owner:
            return []

        creates, alters = self._walk_ast(text)
        if not creates:
            return []

        skipped_lines = self._collect_owner_skip_lines(text)

        # Build a lookup of every ALTER OWNER's qualified name with the
        # matching new owner.  Multiple ALTERs of the same relation are
        # collapsed — we just need to know the eventual owner.
        alter_index: dict[tuple[str, str], str] = {}
        for alter in alters:
            alter_index[(alter.schema, alter.relname)] = alter.new_owner

        violations: list[LintViolation] = []
        for create in creates:
            # Skip the next CREATE after a -- confiture:owner-skip line.
            if create.line in skipped_lines:
                continue

            # Scope: schema in ``apply_to`` and relkind in that schema's set.
            allowed_relkinds = self._scope.get(create.schema)
            if allowed_relkinds is None:
                continue
            if create.relkind not in allowed_relkinds:
                continue

            qualified = f"{create.schema}.{create.relname}"
            if self._matches_ignore(qualified):
                continue

            owner = alter_index.get((create.schema, create.relname))
            if owner == self.expectation.expected_owner:
                continue

            violations.append(
                LintViolation(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    severity=RuleSeverity.ERROR,
                    object_type=_RELKIND_TO_CREATE_LABEL.get(create.relkind, "relation"),
                    object_name=qualified,
                    message=(
                        f"{_RELKIND_TO_CREATE_LABEL.get(create.relkind, 'relation').capitalize()} "
                        f"'{qualified}' was created without "
                        f"`ALTER … OWNER TO {self.expectation.expected_owner};` "
                        f"in the same migration.  Without it, schema-wide GRANTs "
                        f"from the canonical migrator role will fail with "
                        f"`grantor must own the object`."
                    ),
                    file_path=str(path),
                    line_number=create.line,
                )
            )
        return violations

    # ------------------------------------------------------------------ #
    # Directives                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_run_as(text: str) -> str | None:
        """Return the declared role from a top-of-file ``-- confiture:run-as`` directive.

        Scans the file for the directive; the first match wins.  The
        directive may sit anywhere in the file but is typically used as
        front-matter.  Inline trailing comments on a CREATE statement
        are not recognized — the directive must be on its own line.
        """
        for line in text.splitlines():
            m = _RUN_AS_RE.search(line)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def _collect_owner_skip_lines(text: str) -> set[int]:
        """Return the 1-indexed line numbers of CREATE statements opted out.

        A ``-- confiture:owner-skip`` directive attaches to the *next*
        non-blank non-comment line within the file.  This walker returns
        the line numbers of those attached lines so the AST-walk can
        match against ``create.line``.
        """
        skipped: set[int] = set()
        lines = text.splitlines()
        pending_skip = False
        for idx, raw in enumerate(lines, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("--"):
                if _OWNER_SKIP_RE.search(stripped):
                    pending_skip = True
                continue
            if pending_skip:
                skipped.add(idx)
                pending_skip = False
        return skipped

    def _matches_ignore(self, qualified_name: str) -> bool:
        return any(fnmatch.fnmatchcase(qualified_name, p) for p in self.expectation.ignore)

    # ------------------------------------------------------------------ #
    # AST walk                                                            #
    # ------------------------------------------------------------------ #

    def _walk_ast(self, sql: str) -> tuple[list[_CreateRecord], list[_AlterOwnerRecord]]:
        """Parse *sql* via pglast and return its CREATEs and ALTER … OWNER TOs.

        Statements inside ``DO $$ … $$`` blocks are opaque to pglast and
        never appear as top-level statements, so an ``EXECUTE 'ALTER …
        OWNER TO …'`` wrapped in a DO block correctly does NOT count.
        """
        import pglast  # local import — guarded by is_pglast_available() above

        creates: list[_CreateRecord] = []
        alters: list[_AlterOwnerRecord] = []
        try:
            tree = pglast.parse_sql(sql)
        except Exception:
            # Parse failures (templated SQL, exotic dialect quirks)
            # should not crash the lint — just return no findings for
            # this file.  The drift detector will catch real problems
            # at runtime.
            return creates, alters

        for raw in tree or []:
            stmt = raw.stmt
            stmt_location = raw.stmt_location or 0
            # ``stmt_location`` includes any leading comments, so jump
            # forward to the first keyword to report the line accurately.
            keyword_pos = _first_keyword_pos(sql, stmt_location)
            line = sql[:keyword_pos].count("\n") + 1

            cls_name = type(stmt).__name__
            if cls_name == "CreateStmt":
                relation = stmt.relation
                creates.append(
                    _CreateRecord(
                        schema=relation.schemaname or _DEFAULT_SCHEMA,
                        relname=relation.relname,
                        relkind="r",
                        line=line,
                    )
                )
            elif cls_name == "ViewStmt":
                view = stmt.view
                creates.append(
                    _CreateRecord(
                        schema=view.schemaname or _DEFAULT_SCHEMA,
                        relname=view.relname,
                        relkind="v",
                        line=line,
                    )
                )
            elif cls_name == "CreateTableAsStmt":
                # MATERIALIZED VIEW shows up here too; non-matview shape
                # would be a plain SELECT INTO, not in scope.
                objtype = getattr(stmt, "objtype", None)
                objtype_name = getattr(objtype, "name", "") if objtype else ""
                if objtype_name == "OBJECT_MATVIEW":
                    rel = stmt.into.rel
                    creates.append(
                        _CreateRecord(
                            schema=rel.schemaname or _DEFAULT_SCHEMA,
                            relname=rel.relname,
                            relkind="m",
                            line=line,
                        )
                    )
            elif cls_name == "CreateSeqStmt":
                seq = stmt.sequence
                creates.append(
                    _CreateRecord(
                        schema=seq.schemaname or _DEFAULT_SCHEMA,
                        relname=seq.relname,
                        relkind="S",
                        line=line,
                    )
                )
            elif cls_name == "AlterTableStmt":
                # ALTER TABLE / VIEW / MATERIALIZED VIEW / SEQUENCE
                # all produce AlterTableStmt — the rewrite happens at
                # parse time.  Look at each AlterTableCmd for
                # ``AT_ChangeOwner`` (i.e. OWNER TO …).
                relation = stmt.relation
                for cmd in stmt.cmds or ():
                    subtype = getattr(cmd, "subtype", None)
                    subtype_name = getattr(subtype, "name", "") if subtype else ""
                    if subtype_name != "AT_ChangeOwner":
                        continue
                    new_owner_node = getattr(cmd, "newowner", None)
                    role_name = (
                        getattr(new_owner_node, "rolename", None)
                        if new_owner_node is not None
                        else None
                    )
                    if not role_name:
                        continue
                    alters.append(
                        _AlterOwnerRecord(
                            schema=relation.schemaname or _DEFAULT_SCHEMA,
                            relname=relation.relname,
                            new_owner=role_name,
                        )
                    )
        return creates, alters


__all__ = ["Own001OwnershipCoverage"]
