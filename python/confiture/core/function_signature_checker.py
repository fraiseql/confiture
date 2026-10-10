"""Check that function parameter type changes include DROP FUNCTION for old signature.

When a function's parameter types change, PostgreSQL's CREATE OR REPLACE silently
creates a second overload rather than replacing the old one.  This module detects
that case by comparing old vs new routines — the schema model's, read from the
tree the build reads at each ref — and verifying that a migration file drops the
old signature.
"""

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING

import pglast

from confiture.core.ddl_walk import object_edits, object_kinds
from confiture.core.function_body_checker import migration_sql
from confiture.core.function_signature_drift import (
    by_name,
    function_key,
    printed_arguments,
    printed_signature,
    unpaired_routines,
)
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.sql_lexer import parse_file
from confiture.core.type_lattice import signature_from_type_names, signatures_match

if TYPE_CHECKING:
    from collections.abc import Sequence

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

    It compares the routines two trees declare — each ref's build, read whole — so
    a routine that moved between files is compared with itself.
    """

    def check(
        self,
        old_routines: Sequence[Routine],
        new_routines: Sequence[Routine],
        migration_file_paths: list[Path],
    ) -> list[FunctionSignatureViolation]:
        """Each routine whose argument types changed with no migration dropping the old one.

        A routine *old_routines* holds that *new_routines* lacks is retyped when
        *new_routines* gained a routine of the same ``schema.name``; the i-th of a
        name's lost routines is reported against the i-th it gained, or the last. A
        name that only lost an overload, or lost every routine, was dropped: the
        accompaniment check reports that as a schema change.

        Args:
            old_routines: The routines the base tree declares.
            new_routines: The routines the target tree declares.
            migration_file_paths: New migration files in the changeset.

        Returns:
            List of violations (empty if all type changes have accompanying DROPs)
        """
        dropped, added = unpaired_routines(old_routines, new_routines)
        overloads = by_name(old_routines)
        violations: list[FunctionSignatureViolation] = []
        for old, new in _retypes(dropped, added):
            fn_key = function_key(old)
            if _migration_drops(old, migration_file_paths, sole=len(overloads[fn_key]) == 1):
                continue
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


def _retypes(dropped: list[Routine], added: list[Routine]) -> list[tuple[Routine, Routine]]:
    """Each lost routine with the routine of its name that took its place.

    The i-th routine a name lost goes with the i-th it gained, or with the last it
    gained when it gained fewer; a name that gained none was dropped, not retyped.
    """
    gained = by_name(added)
    lost = by_name(dropped)
    return [
        (old, gained[fn_key][min(i, len(gained[fn_key]) - 1)])
        for fn_key, olds in lost.items()
        if fn_key in gained
        for i, old in enumerate(olds)
    ]


def _migration_drops(old: Routine, migration_files: list[Path], *, sole: bool) -> bool:
    """Whether any migration drops *old* — its name and its argument types.

    *sole*: *old* is the one routine of its name the base tree declares, so a
    ``DROP FUNCTION`` naming no argument list drops it.
    """
    for mig_path in migration_files:
        try:
            content = mig_path.read_text()
        except OSError, UnicodeDecodeError:
            continue
        for sql in migration_sql(mig_path, content):
            if _drops(sql, old, sole=sole):
                return True
    return False


def _drops(sql: str, routine: Routine, *, sole: bool) -> bool:
    """Whether *sql* holds a ``DROP FUNCTION`` / ``PROCEDURE`` / ``ROUTINE`` of *routine*.

    A drop that names no argument list drops the one routine of that name, so it
    counts when *routine* is the *sole* one; with two, PostgreSQL refuses it (the
    name is not unique). A schema the drop leaves off matches any, as PostgreSQL resolves it
    through ``search_path``. A migration pglast rejects drops nothing here; the
    migration's own checks report it.
    """
    try:
        statements = parse_file(sql).statements
    except pglast.parser.ParseError:
        return False
    schema = routine.schema or DEFAULT_SCHEMA
    return any(
        edit.kind == "drop"
        and routine.kind in object_kinds(edit.object_kind)
        and edit.name == routine.name
        and edit.schema in (None, schema)
        and (
            sole
            if edit.arg_types is None
            else signatures_match(signature_from_type_names(edit.arg_types), routine.signature_key)
        )
        for raw in statements
        for edit in object_edits(raw.stmt)
    )
