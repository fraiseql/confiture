"""Check that function/procedure body changes include an accompanying migration.

The signature sibling of this check (``FunctionSignatureChecker``) catches
*parameter type* changes that need a ``DROP FUNCTION``. This one catches *body*
changes: a function whose body was edited in the schema DDL (same signature)
without a migration that re-applies it will run the old body in migrate-only
environments (staging/production) — silent prod↔source drift.

Like the signature checker, this is **git-based and static (no database)**: it
compares the routines a file declares at ``base_ref`` and at ``target_ref`` —
the schema model's, read by the lint inventory — and requires a body change to
be carried by a migration that re-defines the function. The complementary
*runtime* guarantee — that the migration actually produces the intended body — is
provided by ``migrate validate --check-body-replay`` (#179).
"""

from __future__ import annotations

import dataclasses
import difflib
from typing import TYPE_CHECKING

import pglast.parser

from confiture.core.function_body_drift import paired
from confiture.core.function_body_normalizer import FunctionBodyNormalizer
from confiture.core.function_signature_drift import (
    declared_routines,
    function_key,
    printed_signature,
)
from confiture.exceptions import GitError

if TYPE_CHECKING:
    from pathlib import Path

    from confiture.core.git import GitRepository
    from confiture.core.schema_model import Routine


@dataclasses.dataclass
class FunctionBodyViolation:
    """A function whose body changed with no accompanying migration.

    Attributes:
        function_key: ``"schema.name"`` (without params).
        signature_key: Full signature, e.g. ``"public.calc(integer)"``.
        migration_file: Always ``None`` (a carrying migration would clear the
            violation); kept for shape-parity with ``FunctionSignatureViolation``.
        message: Human-readable description.
        unified_diff: Diff of the old vs new normalised body (for triage).
    """

    function_key: str
    signature_key: str
    migration_file: str | None
    message: str
    unified_diff: str

    def to_dict(self) -> dict:
        return {
            "function_key": self.function_key,
            "signature_key": self.signature_key,
            "migration_file": self.migration_file,
            "message": self.message,
            "unified_diff": self.unified_diff,
        }


class FunctionBodyChecker:
    """Check that function body changes are carried by a migration.

    Args:
        git_repo: GitRepository for reading file content at refs.
        normalizer: FunctionBodyNormalizer (created if not provided).
    """

    def __init__(
        self,
        git_repo: GitRepository,
        normalizer: FunctionBodyNormalizer | None = None,
    ) -> None:
        self._git = git_repo
        self._normalizer = normalizer or FunctionBodyNormalizer()

    def check(
        self,
        changed_sql_files: list[Path],
        migration_file_paths: list[Path],
        base_ref: str,
        target_ref: str,
    ) -> list[FunctionBodyViolation]:
        """Return body-change violations for the changed SQL files.

        Args:
            changed_sql_files: SQL files that changed between refs.
            migration_file_paths: New migration files in the changeset.
            base_ref: Old git reference.
            target_ref: New git reference.

        Returns:
            One violation per function whose body changed (same signature) with no
            migration re-defining it. Empty if all body changes are carried.
        """
        carried = self._functions_redefined_by_migrations(migration_file_paths)
        violations: list[FunctionBodyViolation] = []
        for sql_file in changed_sql_files:
            old = self._routines_at_ref(sql_file, base_ref)
            new = self._routines_at_ref(sql_file, target_ref)
            violations.extend(self._check_file(old, new, carried))
        return violations

    def _routines_at_ref(self, path: Path, ref: str) -> list[Routine]:
        """The routines *path* declares at *ref*; none when it did not exist there."""
        try:
            content = self._git.show_file_at_ref(path, ref)
        except GitError:
            return []
        if content is None:
            return []
        return declared_routines(content)

    def _check_file(
        self,
        old: list[Routine],
        new: list[Routine],
        carried: set[str],
    ) -> list[FunctionBodyViolation]:
        """A routine both refs declare whose body changed and no migration carries.

        A routine only one ref declares — added, dropped, or given new argument
        types — is not a body change.
        """
        violations: list[FunctionBodyViolation] = []
        for after, before in paired(new, old):
            old_body, new_body = before.body, after.body
            if old_body is None or new_body is None:
                continue  # C/internal — no extractable body to compare
            if self._normalizer.hash_body(old_body) == self._normalizer.hash_body(new_body):
                continue  # body unchanged (modulo comments/whitespace/case)

            fn_key = function_key(after)
            if fn_key in carried:
                continue  # a migration re-defines this function
            sigkey = printed_signature(after)

            violations.append(
                FunctionBodyViolation(
                    function_key=fn_key,
                    signature_key=sigkey,
                    migration_file=None,
                    message=(
                        f"Function body change for {sigkey} detected between refs "
                        f"but no migration re-defines it. Migrate-only environments "
                        f"(staging/production) will keep running the old body. Add a "
                        f"migration with CREATE OR REPLACE FUNCTION {fn_key}(...)."
                    ),
                    unified_diff=self._diff(sigkey, old_body, new_body),
                )
            )
        return violations

    def _diff(self, sigkey: str, old_body: str, new_body: str) -> str:
        old_norm = self._normalizer.normalize_for_diff(old_body)
        new_norm = self._normalizer.normalize_for_diff(new_body)
        return "\n".join(
            difflib.unified_diff(
                old_norm.splitlines(),
                new_norm.splitlines(),
                fromfile=f"{sigkey} (committed)",
                tofile=f"{sigkey} (working)",
                lineterm="",
            )
        )

    def _functions_redefined_by_migrations(self, migration_files: list[Path]) -> set[str]:
        """Return the set of ``function_key`` re-defined by any migration file.

        Read by the lint inventory, as the source is, so a
        ``CREATE [OR REPLACE] FUNCTION`` in a ``.sql`` migration — or inside a
        ``self.execute("…")`` string in a ``.py`` migration — is detected the same
        way, with the same schema-qualification/quoting handling as the source.
        """
        carried: set[str] = set()
        for mig_path in migration_files:
            try:
                content = mig_path.read_text()
            except OSError:
                continue
            for sql in migration_sql(mig_path, content):
                try:
                    routines = declared_routines(sql)
                except pglast.parser.ParseError:
                    # A migration pglast rejects carries nothing here; the
                    # migration's own checks report it as unparseable.
                    continue
                carried.update(function_key(routine) for routine in routines)
        return carried


def migration_sql(path: Path, content: str) -> list[str]:
    """The SQL a migration file carries: the file itself, or a ``.py`` file's snippets."""
    if path.suffix != ".py":
        return [content]
    # Reason: import cycle (the module is partially initialised when this import runs at module level)
    from confiture.core.idempotency.python_migration_extractor import (
        extract_sql_from_python_source,
    )

    return [snippet.sql for snippet in extract_sql_from_python_source(content, path=path).snippets]
