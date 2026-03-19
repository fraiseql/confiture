"""Check that function parameter type changes include DROP FUNCTION for old signature.

When a function's parameter types change, PostgreSQL's CREATE OR REPLACE silently
creates a second overload rather than replacing the old one.  This module detects
that case by comparing old vs new signatures and verifying that a migration file
contains a DROP FUNCTION statement for the old signature.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from confiture.core.function_signature_parser import FunctionSignature, FunctionSignatureParser
from confiture.core.git import GitRepository
from confiture.exceptions import GitError

_DROP_FUNC_RE = re.compile(
    r"DROP\s+(?:FUNCTION|PROCEDURE)\s+.*?\(([^)]*)\)",
    re.IGNORECASE | re.DOTALL,
)


@dataclasses.dataclass
class FunctionSignatureViolation:
    """A function whose parameter type change is missing a DROP FUNCTION migration.

    Attributes:
        function_key: "schema.name" (without params)
        old_signature: Full old signature e.g. "public.get_user(integer)"
        new_signature: Full new signature e.g. "public.get_user(bigint)"
        migration_file: Path of the migration that should contain the DROP, or None
        message: Human-readable description
    """

    function_key: str
    old_signature: str
    new_signature: str
    migration_file: str | None
    message: str

    def to_dict(self) -> dict:
        return {
            "function_key": self.function_key,
            "old_signature": self.old_signature,
            "new_signature": self.new_signature,
            "migration_file": self.migration_file,
            "message": self.message,
        }


class FunctionSignatureChecker:
    """Check that parameter type changes include DROP FUNCTION for old signature.

    Args:
        git_repo: GitRepository instance for reading file content at refs
        parser: FunctionSignatureParser instance (created if not provided)
    """

    def __init__(
        self,
        git_repo: GitRepository,
        parser: FunctionSignatureParser | None = None,
    ) -> None:
        self._git = git_repo
        self._parser = parser or FunctionSignatureParser()

    def check(
        self,
        changed_sql_files: list[Path],
        migration_file_paths: list[Path],
        base_ref: str,
        target_ref: str,
    ) -> list[FunctionSignatureViolation]:
        """Check changed SQL files for signature type changes without DROP.

        Args:
            changed_sql_files: SQL files that changed between refs (relative to repo root)
            migration_file_paths: New migration files in the changeset
            base_ref: Old git reference
            target_ref: New git reference

        Returns:
            List of violations (empty if all type changes have accompanying DROPs)
        """
        violations: list[FunctionSignatureViolation] = []
        for sql_file in changed_sql_files:
            old_sigs = self._get_sigs_at_ref(sql_file, base_ref)
            new_sigs = self._get_sigs_at_ref(sql_file, target_ref)
            violations.extend(self._check_file(old_sigs, new_sigs, migration_file_paths))
        return violations

    def _get_sigs_at_ref(self, path: Path, ref: str) -> list[FunctionSignature]:
        """Retrieve file content at git ref and parse signatures."""
        try:
            content = self._git.show_file_at_ref(path, ref)
        except GitError:
            return []
        if content is None:
            return []
        return self._parser.parse(content)

    def _check_file(
        self,
        old_sigs: list[FunctionSignature],
        new_sigs: list[FunctionSignature],
        migration_files: list[Path],
    ) -> list[FunctionSignatureViolation]:
        """Compare old vs new signatures; for each type change, check migrations."""
        violations: list[FunctionSignatureViolation] = []

        old_by_key = {sig.function_key(): sig for sig in old_sigs}
        new_by_key = {sig.function_key(): sig for sig in new_sigs}

        for fn_key, old_sig in old_by_key.items():
            new_sig = new_by_key.get(fn_key)
            if new_sig is None:
                # Function deleted — not a violation (accompaniment check handles this)
                continue
            if old_sig.param_types == new_sig.param_types:
                # No type change — no violation
                continue

            # Parameter types changed: need DROP FUNCTION(old_types) in a migration
            if not self._migration_has_drop(old_sig, migration_files):
                violations.append(
                    FunctionSignatureViolation(
                        function_key=fn_key,
                        old_signature=old_sig.signature_key(),
                        new_signature=new_sig.signature_key(),
                        migration_file=None,
                        message=(
                            f"Parameter type change for {fn_key} detected "
                            f"({old_sig.param_types} -> {new_sig.param_types}) "
                            f"but no DROP FUNCTION {old_sig.signature_key()} found in migrations."
                        ),
                    )
                )

        return violations

    def _migration_has_drop(
        self,
        old_sig: FunctionSignature,
        migration_files: list[Path],
    ) -> bool:
        """Return True if any migration file has DROP FUNCTION matching old_sig."""
        for mig_path in migration_files:
            try:
                content = mig_path.read_text()
            except OSError:
                continue
            for match in _DROP_FUNC_RE.finditer(content):
                dropped_args_raw = match.group(1)
                dropped_types = self._parse_dropped_types(dropped_args_raw)
                if dropped_types == old_sig.param_types:
                    return True
        return False

    def _parse_dropped_types(self, args_raw: str) -> tuple[str, ...]:
        """Parse the type list from a DROP FUNCTION(...) argument string."""
        if not args_raw.strip():
            return ()
        types = []
        for arg in args_raw.split(","):
            arg = arg.strip()
            if not arg:
                continue
            # DROP FUNCTION takes type-only args (no names), but may have schema: public.integer
            # Normalise each token
            types.append(self._parser._normalise_type(arg))
        return tuple(types)
