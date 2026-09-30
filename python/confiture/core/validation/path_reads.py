"""``migrate validate --check-path-reads``: a migration that reads a schema file (#540).

An applied migration is history, and a file under the schema directories is not:
a replay installs the file's current text, and the file can never be renamed or
removed without breaking the replay (#538). SQL embedded in the migration as module
constants has neither problem.

Which files a migration reads is ``core/migration_reads``'s answer. A read inside
the git scope (``--since``, ``--base-ref``, ``--staged``; every migration when no
scope is given) is a violation. One outside it is reported and does not fail: the
migration is already applied somewhere, and changing it now would change its
checksum; ``migrate squash`` retires it, and with it the pin. A read whose path is not static is reported with the reason, never
counted as clean.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from confiture.core.idempotency.python_migration_extractor import is_migration_file
from confiture.core.migration_reads import MigrationRead, reads, reads_under
from confiture.core.sql_path import find_project_root


@dataclass
class PathReadReport:
    """What the check found across a migrations directory.

    Attributes:
        project_root: What every reported path is shown relative to.
        violations: Reads of a schema file by migrations inside the scope.
        out_of_scope: The same, by migrations outside it.
        unresolved: Reads whose path is not static, in any migration scanned.
        scanned: How many migrations were read.
    """

    project_root: Path
    violations: list[MigrationRead] = field(default_factory=list)
    out_of_scope: list[MigrationRead] = field(default_factory=list)
    unresolved: list[MigrationRead] = field(default_factory=list)
    scanned: int = 0

    def shown(self, path: Path) -> str:
        """``path`` relative to the project root when it is inside it."""
        resolved = path.resolve()
        root = self.project_root.resolve()
        return resolved.relative_to(root).as_posix() if resolved.is_relative_to(root) else str(path)


def check_path_reads(
    migrations_dir: Path,
    schema_dirs: Sequence[Path],
    *,
    in_scope: Collection[Path] | None = None,
    staged_text: Mapping[Path, str] | None = None,
) -> PathReadReport:
    """Every read of a file under ``schema_dirs`` by a ``.py`` migration.

    Args:
        migrations_dir: The migrations directory (a flat listing).
        schema_dirs: The schema directories a read must not reach into.
        in_scope: The migrations whose reads are violations, resolved; ``None``
            puts every migration in scope.
        staged_text: A migration's staged source, read instead of the file.
    """
    report = PathReadReport(project_root=find_project_root(migrations_dir))
    if not migrations_dir.is_dir():
        return report
    scope = None if in_scope is None else {path.resolve() for path in in_scope}
    staged = {path.resolve(): text for path, text in (staged_text or {}).items()}
    for migration in sorted(migrations_dir.glob("*.py")):
        if not is_migration_file(migration):
            continue
        report.scanned += 1
        found = reads(
            migration, project_root=report.project_root, text=staged.get(migration.resolve())
        )
        pinned = reads_under(found, schema_dirs)
        if scope is None or migration.resolve() in scope:
            report.violations.extend(pinned)
        else:
            report.out_of_scope.extend(pinned)
        report.unresolved.extend(read for read in found if read.file is None)
    return report
