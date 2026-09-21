"""Check that function parameter type changes include DROP FUNCTION for old signature.

When a function's parameter types change, PostgreSQL's CREATE OR REPLACE silently
creates a second overload rather than replacing the old one.  This module detects
that case by comparing old vs new routines — the schema model's, read from the
file at each ref by the lint inventory — and verifying that a migration file
drops the old signature.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING

import pglast

from confiture.core.ddl_walk import object_edits, object_kinds
from confiture.core.function_body_checker import migration_sql
from confiture.core.function_signature_drift import (
    by_function,
    declared_routines,
    printed_arguments,
    printed_signature,
)
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.type_lattice import signature_from_type_names, signatures_match
from confiture.exceptions import GitError

if TYPE_CHECKING:
    from confiture.core.git import GitRepository
    from confiture.core.schema_model import Routine


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
    """

    def __init__(self, git_repo: GitRepository) -> None:
        self._git = git_repo

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
            old = self._routines_at_ref(sql_file, base_ref)
            new = self._routines_at_ref(sql_file, target_ref)
            violations.extend(self._check_file(old, new, migration_file_paths))
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
        old_routines: list[Routine],
        new_routines: list[Routine],
        migration_files: list[Path],
    ) -> list[FunctionSignatureViolation]:
        """Compare old vs new routines; for each type change, check migrations.

        A file is read one function at a time: the last overload each declares
        of a ``schema.name``, as a file that redefines a function in place does.
        """
        violations: list[FunctionSignatureViolation] = []
        new_by_fn = by_function(new_routines)

        for fn_key, old_overloads in by_function(old_routines).items():
            new_overloads = new_by_fn.get(fn_key)
            if not new_overloads:
                # Function deleted — not a violation (accompaniment check handles this)
                continue
            old, new = old_overloads[-1], new_overloads[-1]
            if signatures_match(old.signature_key, new.signature_key):
                # No type change — no violation
                continue

            # Parameter types changed: need DROP FUNCTION(old_types) in a migration
            if not self._migration_has_drop(old, migration_files):
                violations.append(
                    FunctionSignatureViolation(
                        function_key=fn_key,
                        old_signature=printed_signature(old),
                        new_signature=printed_signature(new),
                        migration_file=None,
                        message=(
                            f"Parameter type change for {fn_key} detected "
                            f"({printed_arguments(old)} -> {printed_arguments(new)}) "
                            f"but no DROP FUNCTION {printed_signature(old)} found in migrations."
                        ),
                    )
                )

        return violations

    def _migration_has_drop(self, old: Routine, migration_files: list[Path]) -> bool:
        """Whether any migration drops *old* — its name and its argument types."""
        for mig_path in migration_files:
            try:
                content = mig_path.read_text()
            except OSError:
                continue
            for sql in migration_sql(mig_path, content):
                if _drops(sql, old):
                    return True
        return False


def _drops(sql: str, routine: Routine) -> bool:
    """Whether *sql* holds a ``DROP FUNCTION`` / ``PROCEDURE`` / ``ROUTINE`` of *routine*.

    A drop that names no argument list drops the one routine of that name, so it
    counts; a schema the drop leaves off matches any, as PostgreSQL resolves it
    through ``search_path``. A migration pglast rejects drops nothing here; the
    migration's own checks report it.
    """
    try:
        statements = pglast.parse_sql(sql) or ()
    except pglast.parser.ParseError:
        return False
    schema = routine.schema or DEFAULT_SCHEMA
    return any(
        edit.kind == "drop"
        and routine.kind in object_kinds(edit.object_kind)
        and edit.name == routine.name
        and edit.schema in (None, schema)
        and (
            edit.arg_types is None
            or signatures_match(signature_from_type_names(edit.arg_types), routine.signature_key)
        )
        for raw in statements
        for edit in object_edits(raw.stmt)
    )
