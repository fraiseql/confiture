"""Which files a migration reads at run time, and which of them sit under given directories.

A migration that reads ``db/schema/functions/0219_x.sql`` in ``up()`` ties an
entry of an immutable history to a file that keeps changing: a replay installs
the file's current text, not the text the migration shipped with, and renaming
or deleting the file breaks the replay. ``migrate validate --check-path-reads``
reports such reads (#540), and ``generate renumber`` refuses to move a file a
migration reads (#538). Both ask this module.

The paths come from the static evaluator (``ModuleModel.file_reads``). Each is
resolved by ``sql_path.resolve_sql_file``, the resolver the runtime uses, confined
to the project root. A read of a file already gone is still reported, at the path
the project root gives it: the replay is already broken. A path the file does not
fix is reported unresolved, with the evaluator's reason. A ``.sql`` migration reads
no file: its text is its SQL.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from confiture.core.idempotency.static_eval import ModuleModel, PathV, Str, Unknown, Value
from confiture.core.sql_path import find_project_root, resolve_sql_file


@dataclass(frozen=True)
class MigrationRead:
    """One file a migration reads, or one read whose path is not static.

    Attributes:
        migration: The migration file.
        line: The line of the read.
        file: The file read, resolved; ``None`` when the path is not static.
        exists: Whether ``file`` is on disk.
        reason: Why the path is not static, when ``file`` is ``None``.
    """

    migration: Path
    line: int
    file: Path | None
    exists: bool = False
    reason: str | None = None


def reads(
    migration: Path, *, project_root: Path | None = None, text: str | None = None
) -> list[MigrationRead]:
    """Every file ``migration`` reads, in source order, one entry per path.

    Args:
        migration: A ``.py`` migration; any other file reads nothing.
        project_root: Where relative paths start and reads are confined.
            Defaults to the nearest ancestor carrying ``pyproject.toml``,
            ``.git`` or ``db/``.
        text: The migration's source, when it is not the file on disk (a
            staged blob). ``__file__`` is still ``migration``.
    """
    if migration.suffix != ".py":
        return []
    root = project_root if project_root is not None else find_project_root(migration)
    source = text if text is not None else migration.read_text(encoding="utf-8")
    try:
        model = ModuleModel(source, path=migration, project_root=root)
    except SyntaxError as exc:
        return [
            MigrationRead(migration, exc.lineno or 0, None, reason=f"not valid Python: {exc.msg}")
        ]
    return [
        _resolved(migration, site.line, value, root)
        for site in model.file_reads()
        for value in site.values
    ]


def reads_under(found: Iterable[MigrationRead], directories: Sequence[Path]) -> list[MigrationRead]:
    """The reads of a file inside any of ``directories``."""
    bases = [directory.resolve() for directory in directories]
    return [
        read
        for read in found
        if read.file is not None and any(read.file.is_relative_to(base) for base in bases)
    ]


def _resolved(migration: Path, line: int, value: Value, root: Path) -> MigrationRead:
    if isinstance(value, Unknown):
        return MigrationRead(migration, line, None, reason=value.reason)
    if isinstance(value, PathV):
        raw = value.path
    elif isinstance(value, Str):
        raw = Path(value.text)
    else:
        return MigrationRead(migration, line, None, reason="the path is a sequence, not one path")
    resolution = resolve_sql_file(raw, migration_file=migration, project_root=root, confine=True)
    if resolution.outcome == "found":
        assert resolution.path is not None
        return MigrationRead(migration, line, resolution.path, exists=True)
    if resolution.outcome == "escaped":
        return MigrationRead(migration, line, None, reason=f"{raw} resolves outside the project")
    return MigrationRead(migration, line, resolution.tried[0].resolve())
