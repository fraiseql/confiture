"""Check that function/procedure body changes include an accompanying migration.

The signature sibling of this check (``FunctionSignatureChecker``) catches
*parameter type* changes that need a ``DROP FUNCTION``. This one catches *body*
changes: a function whose body was edited in the schema DDL (same signature)
without a migration that re-applies it will run the old body in migrate-only
environments (staging/production) — silent prod↔source drift.

Like the signature checker, this is **static (no database)**: it compares the
routines two trees declare — the schema model's, each ref's build read whole, so
a routine that moved between files is compared with itself — and requires a body change to
be carried by a migration that re-defines the function. The complementary
*runtime* guarantee — that the migration actually produces the intended body — is
provided by ``migrate validate --check-body-replay`` (#179).
"""

import dataclasses
import difflib
from typing import TYPE_CHECKING

from confiture.core.function_body_drift import changed_bodies
from confiture.core.function_body_normalizer import FunctionBodyNormalizer
from confiture.core.function_signature_drift import (
    declared_routines,
    function_key,
    printed_signature,
)
from confiture.exceptions import SchemaError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

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
        normalizer: FunctionBodyNormalizer (created if not provided).
    """

    def __init__(self, normalizer: FunctionBodyNormalizer | None = None) -> None:
        self._normalizer = normalizer or FunctionBodyNormalizer()

    def check(
        self,
        old: Sequence[Routine],
        new: Sequence[Routine],
        migration_file_paths: list[Path],
    ) -> list[FunctionBodyViolation]:
        """A routine both trees declare whose body changed and no migration carries.

        A routine only one tree declares — added, dropped, or given new argument
        types — is not a body change.

        Args:
            old: The routines the base tree declares.
            new: The routines the target tree declares.
            migration_file_paths: New migration files in the changeset.

        Returns:
            One violation per function whose body changed (same signature) with no
            migration re-defining it, in the order the target tree declares them.
        """
        carried = self._functions_redefined_by_migrations(migration_file_paths)
        violations: list[FunctionBodyViolation] = []
        changed, _checked = changed_bodies(old, new)
        order = {id(routine): position for position, routine in enumerate(new)}
        for before, after in sorted(changed, key=lambda pair: order[id(pair[1])]):
            old_body, new_body = before.body, after.body
            if old_body is None or new_body is None:
                continue  # C/internal — no extractable body to compare

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
            except OSError, UnicodeDecodeError:
                continue
            for sql in migration_sql(mig_path, content):
                try:
                    routines = declared_routines(sql)
                except SchemaError:
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
