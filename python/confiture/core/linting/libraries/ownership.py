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


class Own002BareAlterOwner:
    """OWN002 — flag `ALTER … OWNER TO <expected_owner>` on pre-existing objects.

    Closes the PR-time detection loop for issue #137's failure mode:
    a migration tries to "repair" ownership of an object it didn't
    create, but it runs as the non-owning migrator role.

    Three severity tiers per occurrence:

    1. Inside an ``IF EXISTS`` guard AND the migration is
       ``requires_superuser=True`` → silent (intended pattern).
    2. Inside an ``IF EXISTS`` guard but no companion
       ``requires_superuser=True`` → WARNING.
    3. Bare ``ALTER OWNER`` (no guard) → ERROR.

    Detecting ``requires_superuser=True`` looks at the companion
    ``.py`` file (same stem as the ``.up.sql`` migration).  Pure-SQL
    migrations with no companion default to "not superuser."

    Detecting ``IF EXISTS`` guards walks the parent AST tree for an
    enclosing ``DO $$ … IF EXISTS … END IF; … $$`` block.

    AST-only: shares the pglast-required guard with :class:`Own001OwnershipCoverage`.
    """

    rule_id: ClassVar[str] = "own_002"
    rule_name: ClassVar[str] = "Bare ALTER OWNER on pre-existing object"

    def __init__(self, expectation: OwnershipExpectation) -> None:
        self.expectation = expectation
        self._scope_schemas = {entry.schema_ for entry in expectation.apply_to}

    def check(self, migrations_dir: Path) -> list[LintViolation]:
        if not migrations_dir.exists():
            return []
        if not is_pglast_available():
            emit_skip_notice(
                'own_002 requires the [ast] extra: pip install "fraiseql-confiture[ast]"'
            )
            return []

        violations: list[LintViolation] = []
        for migration in sorted(migrations_dir.rglob("*.up.sql")):
            violations.extend(self._check_file(migration))
        return violations

    def _check_file(self, path: Path) -> list[LintViolation]:
        text = path.read_text()
        created, alter_records = self._extract(text)

        # Filter to ALTER OWNER TO <expected_owner> only.
        relevant_alters = [
            (alter, was_guarded)
            for alter, was_guarded in alter_records
            if alter.new_owner == self.expectation.expected_owner
            and alter.schema in self._scope_schemas
        ]
        if not relevant_alters:
            return []

        # An ALTER OWNER paired with a CREATE in the same file is the
        # `own_001`'s domain; we only care about the *bare* case here.
        created_keys = {(c.schema, c.relname) for c in created}

        companion_su = _companion_declares_requires_superuser(path)

        violations: list[LintViolation] = []
        for alter, was_guarded in relevant_alters:
            if (alter.schema, alter.relname) in created_keys:
                continue
            qualified = f"{alter.schema}.{alter.relname}"
            if was_guarded and companion_su:
                # Tier 1: intended pattern; silent.
                continue
            severity = RuleSeverity.WARNING if was_guarded else RuleSeverity.ERROR
            violations.append(
                LintViolation(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    severity=severity,
                    object_type="relation",
                    object_name=qualified,
                    message=_build_own_002_message(
                        qualified=qualified,
                        expected_owner=self.expectation.expected_owner,
                        was_guarded=was_guarded,
                    ),
                    file_path=str(path),
                    line_number=None,
                )
            )
        return violations

    @staticmethod
    def _extract(
        sql: str,
    ) -> tuple[list[_CreateRecord], list[tuple[_AlterOwnerRecord, bool]]]:
        """Parse *sql* and return CREATEs and ALTER OWNERs (each with a guard flag)."""
        import pglast

        creates: list[_CreateRecord] = []
        alters: list[tuple[_AlterOwnerRecord, bool]] = []
        try:
            tree = pglast.parse_sql(sql)
        except Exception:
            return creates, alters

        for raw in tree or []:
            stmt = raw.stmt
            cls_name = type(stmt).__name__

            if cls_name == "CreateStmt":
                relation = stmt.relation
                creates.append(
                    _CreateRecord(
                        schema=relation.schemaname or _DEFAULT_SCHEMA,
                        relname=relation.relname,
                        relkind="r",
                        line=raw.stmt_location or 0,
                    )
                )
            elif cls_name == "AlterTableStmt":
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
                        (
                            _AlterOwnerRecord(
                                schema=relation.schemaname or _DEFAULT_SCHEMA,
                                relname=relation.relname,
                                new_owner=role_name,
                            ),
                            False,  # plain top-level ALTER → not guarded
                        )
                    )
            elif cls_name == "DoStmt":
                # Re-parse the DO block's body string to look for
                # `EXECUTE 'ALTER … OWNER TO …'` patterns inside an
                # IF EXISTS guard.  pglast can't introspect PL/pgSQL
                # bodies (they're opaque strings), so we fall back to
                # a regex pass scoped to this single DO block.
                body = _extract_do_body(stmt)
                if body is None:
                    continue
                alters.extend(_parse_alter_owner_in_do_block(body))
        return creates, alters


def _extract_do_body(do_stmt: object) -> str | None:
    """Return the SQL body string from a pglast DoStmt, or None."""
    for arg in getattr(do_stmt, "args", ()) or ():
        defname = getattr(arg, "defname", None)
        if defname != "as":
            continue
        value = getattr(arg, "arg", None)
        sval = getattr(value, "sval", None) if value is not None else None
        if isinstance(sval, str):
            return sval
    return None


def _parse_alter_owner_in_do_block(
    body: str,
) -> list[tuple[_AlterOwnerRecord, bool]]:
    """Find ``ALTER … OWNER TO …`` references inside a DO block body.

    PL/pgSQL bodies are opaque to pglast — they're the contents of a
    dollar-quoted string.  We do a deliberately narrow regex pass
    keyed on the literal ``ALTER TABLE`` / ``ALTER … OWNER TO`` shape,
    coupled with a separate scan for an enclosing ``IF EXISTS`` token.

    Returns ``(record, was_guarded)`` tuples — ``was_guarded`` is True
    when the body contains an ``IF EXISTS`` token anywhere before the
    ``ALTER … OWNER TO`` text.
    """
    # Simple regex: ALTER TABLE [schema.]name OWNER TO role
    alter_re = re.compile(
        r"ALTER\s+TABLE\s+"
        r"(?:(?P<schema>[A-Za-z_][\w]*)\.)?(?P<name>[A-Za-z_][\w]*)\s+"
        r"OWNER\s+TO\s+(?P<owner>[A-Za-z_][\w]*)",
        re.IGNORECASE,
    )
    found: list[tuple[_AlterOwnerRecord, bool]] = []
    body_upper = body.upper()
    guard_present = "IF EXISTS" in body_upper
    for m in alter_re.finditer(body):
        found.append(
            (
                _AlterOwnerRecord(
                    schema=m.group("schema") or _DEFAULT_SCHEMA,
                    relname=m.group("name"),
                    new_owner=m.group("owner"),
                ),
                guard_present,
            )
        )
    return found


def _companion_declares_requires_superuser(sql_path: Path) -> bool:
    """Return True when the companion ``.py`` migration sets ``requires_superuser = True``.

    Looks for the same-stem ``.py`` file and greps for
    ``requires_superuser\\s*=\\s*True``.  Pure-SQL migrations with no
    companion default to False.
    """
    # ``with_suffix`` on a ``.up.sql`` strips only ``.sql``; reach the
    # ``.py`` companion via name munging instead.
    stem_base = sql_path.name.replace(".up.sql", "")
    py_companion = sql_path.parent / f"{stem_base}.py"
    if not py_companion.exists():
        return False
    try:
        text = py_companion.read_text()
    except OSError:
        return False
    return bool(re.search(r"requires_superuser\s*=\s*True", text))


def _build_own_002_message(*, qualified: str, expected_owner: str, was_guarded: bool) -> str:
    if was_guarded:
        return (
            f"`ALTER TABLE {qualified} OWNER TO {expected_owner}` targets a "
            f"pre-existing object inside an `IF EXISTS` guard.  Mark the "
            f"migration with `requires_superuser = True` so it runs as a "
            f"superuser via `confiture migrate apply-as`, or restructure the "
            f"migration to assume bootstrap has already run."
        )
    return (
        f"`ALTER TABLE {qualified} OWNER TO {expected_owner}` targets a "
        f"pre-existing object with no `IF EXISTS` guard.  The migrator role "
        f"lacks `ALTER OWNER` privilege on objects it didn't create, so this "
        f"migration will fail at apply time.  Either run `confiture bootstrap` "
        f"once during environment setup, or wrap this statement in an "
        f"`IF EXISTS` guard and mark the migration with "
        f"`requires_superuser = True`."
    )


__all__ = ["Own001OwnershipCoverage", "Own002BareAlterOwner"]
