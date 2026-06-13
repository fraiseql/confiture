"""Grant accompaniment validation.

Validates that changes to grant files (db/7_grant/) are carried by an
accompanying migration. Build environments apply grants from the grant
directory automatically; migrate environments (staging, production) only apply
grants when they appear in a migration. This asymmetry causes silent
permission failures in production when grant files are changed without a
migration that carries the change.

The check is **semantic** (issue #162): it verifies that each *changed*
GRANT/REVOKE statement is actually present in an accompanying migration — not
merely that some migration exists in the changeset. When a changed grant can't
be represented statically (dynamic SQL, unmodeled object classes, removed
grants, search_path-relative schemas), it degrades to the previous
file-presence check (a migration must be present) and the reason is surfaced as
a note. It never silently passes an unaccompanied grant.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from confiture.core.git import GitRepository
from confiture.core.idempotency.python_migration_extractor import (
    ExtractionKind,
    extract_sql_from_python_migration,
)
from confiture.core.migration_grant_extractor import (
    GrantStatement,
    MigrationGrantExtractor,
)
from confiture.models.git import GrantAccompanimentReport

# A SET search_path naming a schema outside this set makes unqualified object
# names ambiguous — the extractor would key them as `public`, which can
# false-fail a correct migration. We degrade such grant files instead (D12).
_SEARCH_PATH_RE = re.compile(r"\bSET\s+search_path\s*(?:=|TO)\s*(?P<list>[^;]+)", re.IGNORECASE)
_SEARCH_PATH_SAFE_SCHEMAS = frozenset({"public", "pg_catalog", "$user", '"$user"'})


class GrantAccompanimentChecker:
    """Check that changed grants are carried by an accompanying migration.

    Recognizes both SQL (``.up.sql``) and Python (``.py``) migrations. The
    required set (the *added/changed* grants) is diffed against the merge-base
    of the base and target refs, consistent with three-dot changed-file
    semantics; the covered set is the union of grants found in every
    accompanying migration.

    Attributes:
        repo_path: Repository root directory
        git_repo: GitRepository instance
        grant_dir: Relative path to grant directory (default: "db/7_grant")
        migrations_dir: Relative path to migrations directory (default: "db/migrations")

    Example:
        >>> checker = GrantAccompanimentChecker()
        >>> report = checker.check_accompaniment(staged_only=True)
        >>> if not report.is_valid:
        ...     print(f"Error: {report.summary()}")
    """

    def __init__(
        self,
        repo_path: Path | None = None,
        grant_dir: str = "db/7_grant",
        migrations_dir: str = "db/migrations",
    ):
        """Initialize grant accompaniment checker.

        Args:
            repo_path: Repository root directory (default: current directory)
            grant_dir: Relative path to grant directory (default: "db/7_grant")
            migrations_dir: Relative path to migrations directory (default: "db/migrations")
        """
        self.repo_path = repo_path or Path.cwd()
        self.git_repo = GitRepository(self.repo_path)
        self.grant_dir = grant_dir
        self.migrations_dir = migrations_dir
        self._extractor = MigrationGrantExtractor()

    def check_accompaniment(
        self,
        base_ref: str = "HEAD",
        target_ref: str = "HEAD",
        staged_only: bool = False,
    ) -> GrantAccompanimentReport:
        """Check that grant changes are carried by accompanying migrations.

        When staged_only=True, compares the staging index against HEAD.
        Otherwise, compares ``target_ref`` against the merge-base of
        ``base_ref`` and ``target_ref``.

        Args:
            base_ref: Base git reference (used when staged_only=False)
            target_ref: Target git reference (used when staged_only=False)
            staged_only: If True, check staged files only (pre-commit mode)

        Returns:
            GrantAccompanimentReport with validation results

        Raises:
            NotAGitRepositoryError: If not in a git repository
            GitError: If git operations fail
        """
        if staged_only:
            changed_files = self.git_repo.get_staged_files()
        else:
            changed_files = self.git_repo.get_changed_files(base_ref, target_ref)

        grant_files = self._filter_grant_files(changed_files)
        migration_files = self._filter_migration_files(changed_files)

        report = GrantAccompanimentReport(
            has_grant_changes=len(grant_files) > 0,
            has_migration_changes=len(migration_files) > 0,
            grant_files_changed=grant_files,
            migration_files_staged=migration_files,
        )
        if not grant_files:
            return report

        # The merge-base is the anchor for the required-set content diff (D10).
        merge_base = base_ref if staged_only else self.git_repo.get_merge_base(base_ref, target_ref)

        required, notes = self._compute_required(grant_files, merge_base, target_ref, staged_only)
        covered, covered_notes = self._compute_covered(migration_files, target_ref, staged_only)
        notes.extend(covered_notes)

        unmatched = [stmt for stmt in required if stmt not in covered]
        report.unmatched_grants = [self._serialize_unmatched(stmt) for stmt in unmatched]
        report.unverifiable_notes = notes
        return report

    # ------------------------------------------------------------------ #
    # Required set (changed grants)                                       #
    # ------------------------------------------------------------------ #

    def _compute_required(
        self,
        grant_files: list[Path],
        base_ref: str,
        target_ref: str,
        staged_only: bool,
    ) -> tuple[set[GrantStatement], list[str]]:
        """Return the added/changed grant statements and any degradation notes."""
        required: set[GrantStatement] = set()
        notes: list[str] = []

        for grant_file in grant_files:
            target_content = self._read_at_target(grant_file, target_ref, staged_only)
            base_content = self._read_at_ref(grant_file, base_ref)

            # A grant file whose content we can't read as text degrades to
            # file-presence (keeps MagicMock-based unit tests on this path).
            if not isinstance(target_content, str):
                notes.append(
                    f"{grant_file.as_posix()}: grant content unreadable; relying on migration presence"
                )
                continue

            # A non-public SET search_path makes unqualified objects ambiguous;
            # degrade rather than risk false-failing a correct migration (D12).
            if self._search_path_ambiguous(target_content):
                notes.append(
                    f"{grant_file.as_posix()}: SET search_path makes unqualified grants "
                    "ambiguous; relying on migration presence"
                )
                continue

            target_extraction = self._extractor.extract_grant_statements(target_content)
            base_statements: set[GrantStatement] = set()
            base_options: dict[GrantStatement, bool] = {}
            if isinstance(base_content, str):
                base_extraction = self._extractor.extract_grant_statements(base_content)
                base_statements = set(base_extraction.statements)
                base_options = {s: s.grant_option for s in base_extraction.statements}

            target_statements = set(target_extraction.statements)

            # Newly added / changed grants are the required set.
            for stmt in target_statements - base_statements:
                required.add(stmt)

            # A grant that differs only by WITH GRANT OPTION yields no key
            # change (the flag is out of the match key) — surface it (D9).
            # Iterate the target set so `stmt` is always the target instance.
            for stmt in target_statements:
                if stmt in base_statements and stmt.grant_option != base_options.get(stmt, False):
                    notes.append(
                        f"{grant_file.as_posix()}: {stmt.describe()} — only WITH GRANT OPTION "
                        "changed; relying on migration presence"
                    )

            # A grant removed from the file (present at base, absent at target)
            # degrades to file-presence — v1 does not auto-require a REVOKE (D8).
            for stmt in base_statements - target_statements:
                notes.append(
                    f"{grant_file.as_posix()}: {stmt.describe()} was removed; relying on "
                    "migration presence (no automatic REVOKE-migration requirement)"
                )

            # Surface every grant the extractor couldn't represent (D9).
            for marker in target_extraction.unrepresentable:
                notes.append(f"{grant_file.as_posix()}: {marker.detail} ({marker.reason})")

        return required, notes

    # ------------------------------------------------------------------ #
    # Covered set (accompanying migrations)                               #
    # ------------------------------------------------------------------ #

    def _compute_covered(
        self,
        migration_files: list[Path],
        target_ref: str,
        staged_only: bool,
    ) -> tuple[set[GrantStatement], list[str]]:
        """Return the union of grant statements carried by accompanying migrations."""
        covered: set[GrantStatement] = set()
        notes: list[str] = []

        for migration_file in migration_files:
            if migration_file.name.endswith(".py"):
                stmts, py_notes = self._covered_from_python(migration_file, target_ref, staged_only)
                covered.update(stmts)
                notes.extend(py_notes)
                continue

            content = self._read_at_target(migration_file, target_ref, staged_only)
            if not isinstance(content, str):
                continue
            extraction = self._extractor.extract_grant_statements(content)
            covered.update(extraction.statements)

        return covered, notes

    def _covered_from_python(
        self,
        migration_file: Path,
        target_ref: str,
        staged_only: bool,
    ) -> tuple[set[GrantStatement], list[str]]:
        """Extract grant statements carried by a Python migration at the right ref (D11)."""
        covered: set[GrantStatement] = set()
        notes: list[str] = []

        content = self._read_at_target(migration_file, target_ref, staged_only)
        if not isinstance(content, str):
            return covered, notes

        # python_migration_extractor reads from disk, so materialize the blob
        # at the target ref to a temp file (D11). execute_file() targets still
        # resolve against the working tree — pass the real repo root and note it.
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td) / migration_file.name
                tmp.write_text(content, encoding="utf-8")
                result = extract_sql_from_python_migration(tmp, project_root=self.repo_path)
        except Exception:  # noqa: BLE001 — never let a migration crash the gate
            notes.append(f"{migration_file.as_posix()}: could not statically extract SQL")
            return covered, notes

        for warning in result.warnings:
            notes.append(f"{migration_file.as_posix()}: {warning.message}")
        for snippet in result.snippets:
            if snippet.kind == ExtractionKind.FILE:
                notes.append(
                    f"{migration_file.as_posix()}: execute_file target read from the working "
                    "tree, not the validated ref"
                )
            extraction = self._extractor.extract_grant_statements(snippet.sql)
            covered.update(extraction.statements)
            for marker in extraction.unrepresentable:
                notes.append(f"{migration_file.as_posix()}: {marker.detail} ({marker.reason})")

        return covered, notes

    # ------------------------------------------------------------------ #
    # Content reading                                                     #
    # ------------------------------------------------------------------ #

    def _read_at_target(self, path: Path, target_ref: str, staged_only: bool) -> str | None:
        """Read a file's content at the target (staged index or target ref)."""
        if staged_only:
            return self.git_repo.get_staged_file_content(path)
        return self.git_repo.get_file_at_ref(path, target_ref)

    def _read_at_ref(self, path: Path, ref: str) -> str | None:
        """Read a file's content at a committed ref (the diff base)."""
        return self.git_repo.get_file_at_ref(path, ref)

    @staticmethod
    def _search_path_ambiguous(content: str) -> bool:
        """True if a SET search_path names a schema outside the safe defaults."""
        for match in _SEARCH_PATH_RE.finditer(content):
            for raw in match.group("list").split(","):
                schema = raw.strip().strip('"').strip("'").lower()
                if schema and schema.strip('"') not in _SEARCH_PATH_SAFE_SCHEMAS:
                    return True
        return False

    @staticmethod
    def _serialize_unmatched(stmt: GrantStatement) -> dict[str, Any]:
        return {
            "statement": stmt.describe(),
            "action": stmt.action,
            "objtype": stmt.objtype,
            "target_kind": stmt.target_kind,
            "schema": stmt.schema,
            "object": stmt.object,
            "grantee": stmt.grantee,
            "privilege": stmt.privilege,
        }

    # ------------------------------------------------------------------ #
    # File filtering                                                      #
    # ------------------------------------------------------------------ #

    def _filter_grant_files(self, files: list[Path]) -> list[Path]:
        """Filter to files under grant_dir.

        Args:
            files: List of file paths to filter

        Returns:
            Files that are under the grant directory
        """
        grant_parts = Path(self.grant_dir).parts
        result = []
        for f in files:
            # Check if file path starts with the grant_dir parts
            if f.parts[: len(grant_parts)] == grant_parts:
                result.append(f)
        return result

    def _filter_migration_files(self, files: list[Path]) -> list[Path]:
        """Filter to migration files under migrations_dir.

        Recognizes both SQL (``.up.sql``) and Python (``.py``) migrations,
        matching the canonical migration loader (``_migrator/discovery.py``)
        and ``MigrationAccompanimentChecker._get_new_migrations``: a ``.py``
        file counts as a migration unless its name starts with ``_`` (which
        excludes ``__init__.py`` and private helper modules). Migrate
        environments apply both formats, so both must satisfy the gate.

        Args:
            files: List of file paths to filter

        Returns:
            Files that are migration files under the migrations directory
        """
        migrations_parts = Path(self.migrations_dir).parts
        result = []
        for f in files:
            if f.parts[: len(migrations_parts)] != migrations_parts:
                continue
            is_sql = f.name.endswith(".up.sql")
            # "not _-prefixed" excludes __init__.py and _helpers.py. Parity
            # with the loader: a migration the loader would run must count.
            is_py = f.name.endswith(".py") and not f.name.startswith("_")
            if is_sql or is_py:
                result.append(f)
        return result
