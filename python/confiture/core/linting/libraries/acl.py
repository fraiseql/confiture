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
from confiture.core.migration_grant_extractor import (
    MigrationGrantExtractor,
    _parse_qualified_name,
)

# Directive marker: a single-line comment whose first non-whitespace
# tokens are ``confiture:owner-only``.  Trailing characters on the line
# are ignored so a follow-on comment ("-- confiture:owner-only — audit
# table") still matches.
_OWNER_ONLY_RE = re.compile(r"--\s*confiture:owner-only\b", re.IGNORECASE)
# Capture the relname from the line that starts a CREATE TABLE.  Anchored
# to the start of line so we can pair each match with its line number for
# the directive walk-back.
_CREATE_TABLE_STMT_RE = re.compile(
    r"""
    ^\s*CREATE\s+
    (?:(?:GLOBAL|LOCAL)\s+)?
    (?:(?:TEMP(?:ORARY)?|UNLOGGED)\s+)?
    TABLE\s+
    (?:IF\s+NOT\s+EXISTS\s+)?
    (?P<qname>(?:"[^"]+"|\w+)(?:\.(?:"[^"]+"|\w+))?)
    """,
    re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)


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


def _collect_owner_only_relnames(text: str) -> set[tuple[str, str]]:
    """Return the set of ``(schema, relname)`` pairs opted out by the directive.

    Walks every ``CREATE TABLE`` statement in *text*, captures its
    relname, and checks the immediately-preceding contiguous comment
    block for ``-- confiture:owner-only``.  Built once per file so the
    coverage check stays O(N) instead of O(N²) substring scans.

    The directive applies only to the CREATE TABLE on the line directly
    after the comment block — adjacent or substring-prefix relnames are
    correctly distinguished.  Inline directives (``-- confiture:owner-only``
    on the same line as the CREATE TABLE) and block-comment forms
    (``/* confiture:owner-only */``) are NOT recognized — the directive
    must be on its own ``--`` line above the statement.
    """
    opted_out: set[tuple[str, str]] = set()
    for m in _CREATE_TABLE_STMT_RE.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        if _has_owner_only_directive(text, table_line=line_no):
            opted_out.add(_parse_qualified_name(m.group("qname")))
    return opted_out


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

        for migration in self._migration_files(migrations_dir):
            text = self._migration_sql_text(migration)
            creates = self._extractor.extract_creates(text)
            drops = self._extractor.extract_drops(text)
            grants = self._extractor.extract_grants(text)
            file_owner_only = _collect_owner_only_relnames(text)

            # Net out tables that are created and dropped in the same file.
            for s, t in drops:
                creates = [c for c in creates if c != (s, t)]

            for schema, table in creates:
                created.append((schema, table, migration))
                if (schema, table) in file_owner_only:
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

    @staticmethod
    def _migration_files(migrations_dir: Path) -> list[Path]:
        """Migration files to scan: ``.up.sql`` plus ``.py`` (issue #162 twin gap).

        Recognizes Python migrations the same way the loader does — excluding
        ``__init__.py`` and ``_``-prefixed helper modules — so a CREATE/GRANT
        carried by a Python migration is no longer a blind spot in the ACL lint.
        """
        sql = sorted(migrations_dir.rglob("*.up.sql"))
        py = sorted(
            f
            for f in migrations_dir.rglob("*.py")
            if f.name != "__init__.py" and not f.name.startswith("_")
        )
        return sql + py

    def _migration_sql_text(self, migration: Path) -> str:
        """Return the SQL text of a migration, statically extracting from ``.py``.

        For Python migrations the resolvable ``self.execute(...)`` /
        ``self.execute_file(...)`` snippets are concatenated; dynamic SQL is
        invisible to static parsing and simply isn't scanned (consistent with
        the rest of the lint).
        """
        if migration.name.endswith(".py"):
            from confiture.core.idempotency.python_migration_extractor import (  # noqa: PLC0415
                extract_sql_from_python_migration,
            )

            try:
                result = extract_sql_from_python_migration(migration)
            except Exception:  # noqa: BLE001 — never let a migration break the lint
                return ""
            return "\n".join(snippet.sql for snippet in result.snippets)
        return migration.read_text()

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
