"""Lint rule for ACL coverage of migration files (ACL001).

ACL001 fires when a migration creates a table that is in scope of the
configured ``acls:`` block but has no matching ``GRANT`` either in the
same migration file or in the configured global grant sweep directory
(typically ``db/7_grant/``).

Pattern: real checker classes with ``.check()`` methods (mirrors
``libraries/generate.py``), not the data-only ``Rule`` metadata pattern
used by ``libraries/gdpr.py`` and friends.

The inverse direction — *"grants changed without a matching migration"*
— is handled by :mod:`confiture.core.grant_accompaniment` (issue #66).
They share the same ``7_grant/`` convention but no parsing surface.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from confiture.config.environment import AclExpectation, AclGrant
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity
from confiture.core.migration_grant_extractor import MigrationGrantExtractor

_OWNER_ONLY_RE = re.compile(r"--\s*confiture:owner-only", re.IGNORECASE)
_CREATE_TABLE_LINE_RE = re.compile(r"^\s*CREATE\s+TABLE\b", re.IGNORECASE | re.MULTILINE)


def _has_owner_only_directive(text: str, table_line: int) -> bool:
    """Return ``True`` if a ``-- confiture:owner-only`` directive sits in the
    contiguous comment block immediately preceding ``table_line``.

    The check walks backwards from ``table_line - 1`` (1-indexed), skipping
    blank lines and lines that start with ``--``.  As soon as it hits a
    non-comment non-blank line, it stops.  Any owner-only directive found
    along the way opts the table out.

    Line-based scan (not AST) because pglast doesn't preserve comment
    proximity reliably and ``pg_format`` re-indents in ways that would
    break a strict "literally the previous line" rule.
    """
    lines = text.splitlines()
    i = table_line - 2  # 0-indexed, line above the CREATE TABLE
    while i >= 0:
        stripped = lines[i].strip()
        if not stripped:
            i -= 1
            continue
        if stripped.startswith("--"):
            if _OWNER_ONLY_RE.search(stripped):
                return True
            i -= 1
            continue
        # Non-comment, non-blank → contiguous block ended.
        return False
    return False


def _matches_apply_to(
    relname: str,
    apply_to: str | list[str],
    ignore: list[str],
) -> bool:
    """Return ``True`` iff *relname* is in scope of *apply_to* but not in *ignore*."""
    if apply_to != "ALL_TABLES":
        patterns = list(apply_to)
        if not any(fnmatch.fnmatchcase(relname, p) for p in patterns):
            return False
    return not any(fnmatch.fnmatchcase(relname, p) for p in ignore)


def _load_global_grants(
    grant_dir: Path | None,
    extractor: MigrationGrantExtractor,
) -> list[tuple[str, str, str, frozenset[str]]]:
    """Read every ``*.sql`` in *grant_dir* and extract ``(schema, table, role, privs)``."""
    if grant_dir is None or not grant_dir.exists():
        return []
    grants: list[tuple[str, str, str, frozenset[str]]] = []
    for sql_file in sorted(grant_dir.rglob("*.sql")):
        if not sql_file.is_file():
            continue
        grants.extend(extractor.extract_grants(sql_file.read_text()))
    return grants


class Acl001GrantCoverage:
    """ACL001 — every created table must have a matching grant.

    The rule is a no-op when ``expectations`` is empty, so projects
    without an ``acls:`` block see zero change.

    Args:
        expectations: Parsed ``acls:`` block from the environment config.
        grant_dir: Directory of global grant sweep files (typically
            ``db/7_grant``); ``None`` to disable.

    Example::

        from pathlib import Path
        from confiture.config.environment import Environment
        from confiture.core.linting.libraries.acl import Acl001GrantCoverage

        env = Environment.load("local")
        rule = Acl001GrantCoverage(
            expectations=env.acls,
            grant_dir=Path("db/7_grant"),
        )
        for v in rule.check(Path("db/migrations")):
            print(v)
    """

    rule_id = "acl_001"
    rule_name = "ACL Grant Coverage"

    def __init__(
        self,
        expectations: list[AclExpectation],
        grant_dir: Path | None = None,
    ) -> None:
        self.expectations = expectations
        self.grant_dir = grant_dir
        self._extractor = MigrationGrantExtractor()

    def check(self, migrations_dir: Path) -> list[LintViolation]:
        """Return one violation per ``(table, role, missing-privileges)`` gap."""
        if not self.expectations:
            return []
        if not migrations_dir.exists():
            return []

        # Build the index of (schema, table) → grants seen in any migration.
        covered: dict[tuple[str, str], set[tuple[str, str]]] = {}
        created: list[tuple[str, str, Path]] = []  # (schema, table, migration file)
        owner_only: set[tuple[str, str]] = set()

        for migration in sorted(migrations_dir.rglob("*.up.sql")):
            text = migration.read_text()
            creates = self._extractor.extract_creates(text)
            drops = self._extractor.extract_drops(text)
            grants = self._extractor.extract_grants(text)

            # Net out tables that are created and dropped in the same file.
            for s, t in drops:
                creates = [c for c in creates if c != (s, t)]

            for schema, table in creates:
                created.append((schema, table, migration))
                if self._is_owner_only(text, table):
                    owner_only.add((schema, table))

            for schema, table, role, privs in grants:
                covered.setdefault((schema, table), set()).update((role, p) for p in privs)

        # Layer in the global grant sweep (db/7_grant/*.sql).
        for schema, table, role, privs in _load_global_grants(self.grant_dir, self._extractor):
            covered.setdefault((schema, table), set()).update((role, p) for p in privs)

        # Now compare each created (in-scope) table against expectations.
        violations: list[LintViolation] = []
        for schema, table, migration in created:
            if (schema, table) in owner_only:
                continue
            for expectation in self.expectations:
                if expectation.schema_ != schema:
                    continue
                if not _matches_apply_to(table, expectation.apply_to, expectation.ignore):
                    continue
                for grant in expectation.grants:
                    missing = [
                        p
                        for p in grant.privileges
                        if (grant.role, p) not in covered.get((schema, table), set())
                    ]
                    if missing:
                        violations.append(
                            self._format_violation(
                                schema=schema,
                                table=table,
                                grant=grant,
                                missing=missing,
                                migration=migration,
                            )
                        )
        return violations

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _is_owner_only(self, text: str, table: str) -> bool:
        """Check the magic-comment opt-out for one ``CREATE TABLE`` line."""
        target_relname = table.lower()
        for m in _CREATE_TABLE_LINE_RE.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            # Cheap check: extract just enough to know which table this line refers to.
            # Reusing the extractor would re-parse the whole file; for the magic-comment
            # path a line-level lookahead is sufficient.
            tail = text[m.start() : m.end() + 200]
            if target_relname not in tail.lower():
                continue
            if _has_owner_only_directive(text, table_line=line_no):
                return True
        return False

    def _format_violation(
        self,
        schema: str,
        table: str,
        grant: AclGrant,
        missing: list[str],
        migration: Path,
    ) -> LintViolation:
        return LintViolation(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=RuleSeverity.ERROR,
            object_type="table",
            object_name=f"{schema}.{table}",
            message=(
                f"Role '{grant.role}' is missing grant(s) "
                f"{', '.join(sorted(missing))} on '{schema}.{table}'. "
                f"Add a `GRANT {', '.join(sorted(missing))} ON {schema}.{table} "
                f"TO {grant.role};` to {migration.name} or to the global grant "
                f"sweep directory."
            ),
            file_path=str(migration),
        )


__all__ = [
    "Acl001GrantCoverage",
    "_has_owner_only_directive",
]
