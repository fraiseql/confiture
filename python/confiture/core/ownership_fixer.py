"""Auto-fixer for ownership coverage gaps in migration files (issue #124).

For each ``CREATE { TABLE | VIEW | MATERIALIZED VIEW | SEQUENCE }`` in
scope of an :class:`OwnershipExpectation` that lacks a matching
``ALTER … OWNER TO <expected_owner>`` later in the same file, the fixer
inserts the missing ``ALTER`` on the line immediately following the
closing ``;`` of the offending ``CREATE``.

Detection delegates to :class:`Own001OwnershipCoverage` so the static
lint rule and the fixer always agree on what's a violation.

AST-only: the fixer is a no-op when pglast is unavailable (delegating to
the rule's skip-notice path).  The lint rule and fixer share that
constraint by design — a partial regex-based fixer would silently miss
violations that the AST detector would catch, leading to confusing
"fix → re-validate → still flagged" cycles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from confiture.config.environment import OwnershipExpectation
from confiture.core.linting._ast_required import is_pglast_available
from confiture.core.linting.libraries.ownership import Own001OwnershipCoverage

# Map the per-relkind statement to the ALTER form that PostgreSQL accepts.
# Sequences need ``ALTER SEQUENCE``, materialized views need
# ``ALTER MATERIALIZED VIEW`` — ``ALTER TABLE`` only works for tables.
_RELKIND_TO_ALTER_FORM: dict[str, str] = {
    "r": "TABLE",
    "v": "VIEW",
    "m": "MATERIALIZED VIEW",
    "S": "SEQUENCE",
}

_RELKIND_TO_KIND_LABEL: dict[str, str] = {
    "r": "TABLE",
    "v": "VIEW",
    "m": "MATERIALIZED VIEW",
    "S": "SEQUENCE",
}


@dataclass(frozen=True)
class FixCandidate:
    """One missing ``ALTER … OWNER TO`` to be emitted."""

    file: Path
    line: int  # 1-indexed line of the CREATE
    qualified_name: str  # ``schema.relname``
    kind: str  # ``TABLE``, ``VIEW``, ``MATERIALIZED VIEW``, ``SEQUENCE``


@dataclass(frozen=True)
class FixPreview:
    """Diff entry: what the fixer would change in one file."""

    file: Path
    before: str
    after: str


class OwnershipFixer:
    """Emit missing ``ALTER … OWNER TO`` statements for an expectation.

    Args:
        expectation: Parsed ``ownership:`` block.

    Example::

        from confiture.config.environment import Environment
        from confiture.core.ownership_fixer import OwnershipFixer

        env = Environment.load("local")
        if env.ownership is not None:
            fixer = OwnershipFixer(expectation=env.ownership)
            changed = fixer.apply(Path("db/migrations"))
            for path in changed:
                print(f"fixed {path}")
    """

    def __init__(self, expectation: OwnershipExpectation) -> None:
        self.expectation = expectation
        self._rule = Own001OwnershipCoverage(expectation=expectation)

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def iter_candidates(self, migrations_dir: Path) -> list[FixCandidate]:
        """Return one :class:`FixCandidate` per uncovered CREATE in *migrations_dir*."""
        if not is_pglast_available():
            return []
        candidates: list[FixCandidate] = []
        for migration in sorted(migrations_dir.rglob("*.up.sql")):
            text = migration.read_text()
            for create, kind in self._uncovered_creates(text):
                candidates.append(
                    FixCandidate(
                        file=migration,
                        line=create.line,
                        qualified_name=f"{create.schema}.{create.relname}",
                        kind=_RELKIND_TO_KIND_LABEL[kind],
                    )
                )
        return candidates

    def preview(self, migrations_dir: Path) -> list[FixPreview]:
        """Return one :class:`FixPreview` per file that would be modified."""
        if not is_pglast_available():
            return []
        previews: list[FixPreview] = []
        for migration in sorted(migrations_dir.rglob("*.up.sql")):
            original = migration.read_text()
            fixed = self.fix_text(original)
            if fixed != original:
                previews.append(FixPreview(file=migration, before=original, after=fixed))
        return previews

    def apply(self, migrations_dir: Path) -> list[Path]:
        """Apply fixes in place to every file that needs one.

        Returns the list of files that were modified.  Files unchanged
        by the fix are not touched.
        """
        if not is_pglast_available():
            return []
        modified: list[Path] = []
        for migration in sorted(migrations_dir.rglob("*.up.sql")):
            original = migration.read_text()
            fixed = self.fix_text(original)
            if fixed != original:
                migration.write_text(fixed)
                modified.append(migration)
        return modified

    def fix_text(self, sql: str) -> str:
        """Return *sql* with missing ``ALTER … OWNER TO`` statements inserted.

        Stable when re-run: applying ``fix_text`` to its own output is a
        no-op because re-detection sees the freshly-emitted ``ALTER``
        and skips the same line on the next pass.
        """
        if not is_pglast_available():
            return sql
        # The rule's AST walk gives us schema/relname/relkind/line for
        # every CREATE.  We sort top-down (largest line first) so we
        # can insert without invalidating earlier line numbers.
        uncovered = self._uncovered_creates(sql)
        if not uncovered:
            return sql

        lines = sql.splitlines(keepends=True)
        # Reverse-order insertion: largest line number first so the
        # insertion offsets of earlier inserts don't shift later ones.
        for create, kind in sorted(uncovered, key=lambda x: x[0].line, reverse=True):
            insert_idx = self._find_statement_end_line(lines, create.line)
            qualified = f"{create.schema}.{create.relname}"
            alter_form = _RELKIND_TO_ALTER_FORM[kind]
            indent = self._leading_indent(lines, create.line - 1)
            alter_line = (
                f"{indent}ALTER {alter_form} {qualified} "
                f"OWNER TO {self.expectation.expected_owner};\n"
            )
            lines.insert(insert_idx, alter_line)
        return "".join(lines)

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    def _uncovered_creates(self, sql: str) -> list[tuple[_CreateRecord, str]]:
        """Return ``(create_record, relkind)`` pairs lacking ALTER OWNER coverage.

        Honours the rule's full scope/ignore/directive logic — including
        the file-level ``-- confiture:run-as`` directive and
        per-statement ``-- confiture:owner-skip``.
        """
        # We re-implement the matching loop here (rather than call
        # rule.check()) because we need the AST records, not the
        # LintViolation objects.  Both code paths share the same helpers.
        if not self.expectation.lint_enabled:
            return []
        run_as = self._rule._extract_run_as(sql)
        if run_as == self.expectation.expected_owner:
            return []

        creates, alters = self._rule._walk_ast(sql)
        if not creates:
            return []

        skipped_lines = self._rule._collect_owner_skip_lines(sql)
        alter_index: dict[tuple[str, str], str] = {
            (a.schema, a.relname): a.new_owner for a in alters
        }

        result: list[tuple[_CreateRecord, str]] = []
        for create in creates:
            if create.line in skipped_lines:
                continue
            allowed = self._rule._scope.get(create.schema)
            if allowed is None or create.relkind not in allowed:
                continue
            qualified = f"{create.schema}.{create.relname}"
            if self._rule._matches_ignore(qualified):
                continue
            if alter_index.get((create.schema, create.relname)) == self.expectation.expected_owner:
                continue
            result.append((create, create.relkind))
        return result

    @staticmethod
    def _find_statement_end_line(lines: list[str], create_line: int) -> int:
        """Return the 0-indexed list-position just past the CREATE's terminating semicolon.

        ``create_line`` is 1-indexed.  Walks forward from that line
        looking for the first ``;`` that isn't inside a string literal —
        a simple state machine is enough for the well-formed migration
        files this fixer ever sees in practice.
        """
        idx = create_line - 1
        in_single = False
        in_double = False
        while idx < len(lines):
            line = lines[idx]
            for ch in line:
                if ch == "'" and not in_double:
                    in_single = not in_single
                elif ch == '"' and not in_single:
                    in_double = not in_double
                elif ch == ";" and not in_single and not in_double:
                    return idx + 1
            idx += 1
        return len(lines)

    @staticmethod
    def _leading_indent(lines: list[str], idx: int) -> str:
        """Return the leading whitespace of ``lines[idx]`` (empty when idx out of range)."""
        if 0 <= idx < len(lines):
            m = re.match(r"[ \t]*", lines[idx])
            if m:
                return m.group(0)
        return ""


# Re-export the rule's record types under the names the fixer uses.  Kept
# at module-bottom so the type-checker still sees the proper class — the
# import is lazy to avoid a circular-import surface.
from confiture.core.linting.libraries.ownership import _CreateRecord  # noqa: E402

__all__ = ["FixCandidate", "FixPreview", "OwnershipFixer"]
