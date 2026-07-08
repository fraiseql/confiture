"""Check that function/procedure body changes include an accompanying migration.

The signature sibling of this check (``FunctionSignatureChecker``) catches
*parameter type* changes that need a ``DROP FUNCTION``. This one catches *body*
changes: a function whose body was edited in the schema DDL (same signature)
without a migration that re-applies it will run the old body in migrate-only
environments (staging/production) — silent prod↔source drift.

Like the signature checker, this is **git-based and static (no database)**: it
compares bodies between ``base_ref`` and ``target_ref`` and requires the change
to be carried by a migration that re-defines the function. The complementary
*runtime* guarantee — that the migration actually produces the intended body — is
provided by ``migrate validate --check-body-replay`` (#179).
"""

from __future__ import annotations

import dataclasses
import difflib
from typing import TYPE_CHECKING

from confiture.core.function_body_normalizer import FunctionBodyNormalizer
from confiture.core.function_signature_parser import FunctionSignatureParser
from confiture.exceptions import GitError

if TYPE_CHECKING:
    from pathlib import Path

    from confiture.core.function_signature_parser import FunctionSignature
    from confiture.core.git import GitRepository


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
        parser: FunctionSignatureParser (created if not provided).
        normalizer: FunctionBodyNormalizer (created if not provided).
    """

    def __init__(
        self,
        git_repo: GitRepository,
        parser: FunctionSignatureParser | None = None,
        normalizer: FunctionBodyNormalizer | None = None,
    ) -> None:
        self._git = git_repo
        self._parser = parser or FunctionSignatureParser()
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
            old = self._bodies_at_ref(sql_file, base_ref)
            new = self._bodies_at_ref(sql_file, target_ref)
            violations.extend(self._check_file(old, new, carried))
        return violations

    def _bodies_at_ref(
        self, path: Path, ref: str
    ) -> dict[str, tuple[FunctionSignature, str | None]]:
        """Return ``{signature_key: (sig, body)}`` for functions in *path* at *ref*."""
        try:
            content = self._git.show_file_at_ref(path, ref)
        except GitError:
            return {}
        if content is None:
            return {}
        return {
            sig.signature_key(): (sig, body)
            for sig, body in self._parser.parse_with_bodies(content)
        }

    def _check_file(
        self,
        old: dict[str, tuple[FunctionSignature, str | None]],
        new: dict[str, tuple[FunctionSignature, str | None]],
        carried: set[str],
    ) -> list[FunctionBodyViolation]:
        violations: list[FunctionBodyViolation] = []
        for sigkey, (sig, new_body) in new.items():
            if sigkey not in old:
                continue  # new overload/function — not a body change
            _old_sig, old_body = old[sigkey]
            if old_body is None or new_body is None:
                continue  # C/internal — no extractable body to compare
            if self._normalizer.hash_body(old_body) == self._normalizer.hash_body(new_body):
                continue  # body unchanged (modulo comments/whitespace/case)

            fn_key = sig.function_key()
            if fn_key in carried:
                continue  # a migration re-defines this function

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

        Reuses :meth:`FunctionSignatureParser.parse_with_bodies` so a
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
            for sig, _body in self._parser.parse_with_bodies(content):
                carried.add(sig.function_key())
        return carried
