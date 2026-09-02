"""Where does a SQL-file path written in a migration point? One answer.

A Python migration names files three ways — ``self.execute_file("db/schema/fn.sql")``,
``self.execute(Path("db/schema/fn.sql").read_text())`` and the path arithmetic
the static evaluator folds — and three parts of confiture used to decide,
each on its own, which file that is: the runtime's ``execute_file`` (cwd only),
the idempotency extractor (cwd, then the migration's directory) and the import
checker's IMP010 (cwd only, literals only). They disagreed with each other, and
all three were wrong from any working directory but the project root: the
documented form is written against the project root, and cwd was only ever a
proxy for it. The gate could verify one file while the deploy executed another.

:func:`resolve_sql_file` is now the only function that turns such a path into a
file, and :func:`find_project_root` the only one that decides what "the project
root" means. The order is **project root → the migration's directory → cwd**;
the first candidate that is a file wins. Under ``confine=True`` (every static
analyzer) the winner must also lie inside the project root after symlinks are
resolved — the v0.8.4 path-traversal hardening, unchanged — and ``escaped`` is
reported only when *no* existing candidate lies inside, so an out-of-root cwd
hit can never shadow an in-root file. The runtime does not confine: it is
already executing arbitrary migration Python, and a boundary there would be
theatre.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PROJECT_ROOT_ANCHORS: tuple[str, ...] = ("pyproject.toml", ".git", "db")
"""A directory carrying any of these is a project root. Nearest ancestor wins."""

Outcome = Literal["found", "missing", "escaped"]


@dataclass(frozen=True)
class SqlFileResolution:
    """What :func:`resolve_sql_file` decided, and what it looked at.

    Attributes:
        outcome: ``found`` — ``path`` is the file to read. ``missing`` — no
            candidate is a file. ``escaped`` — at least one candidate is a file,
            but every one of them resolves outside the project root (only
            possible under ``confine=True``).
        path: The chosen file, fully resolved (symlinks followed), or ``None``.
        tried: Every candidate in the order it was considered, absolute paths
            as-is and relative ones joined to their base. For the ``missing``
            message: it names each base without the caller having to know the
            order.
    """

    outcome: Outcome
    path: Path | None
    tried: tuple[Path, ...]


def find_project_root(start: Path) -> Path:
    """The nearest ancestor of ``start`` carrying a :data:`PROJECT_ROOT_ANCHORS` entry.

    ``start`` may be a file (its directory is where the search begins) or a
    directory (searched itself first). Falls back to that starting directory
    when no ancestor carries an anchor, so a lone migration in ``/tmp`` still
    gets a boundary — its own directory — rather than none.

    Independent of the working directory: only ``start`` and its ancestors are
    consulted.
    """
    base = start.resolve()
    if not base.is_dir():
        base = base.parent
    for ancestor in (base, *base.parents):
        if any((ancestor / anchor).exists() for anchor in PROJECT_ROOT_ANCHORS):
            return ancestor
    return base


def resolve_sql_file(
    raw: str | Path,
    *,
    migration_file: Path | None,
    project_root: Path | None,
    confine: bool,
) -> SqlFileResolution:
    """Turn a path as written in a migration into the file it names.

    Args:
        raw: The path as written — absolute, or relative to the project.
        migration_file: The migration that wrote it, or ``None`` when the
            caller has no file (a migration class built in memory). Its
            directory is the second base tried.
        project_root: The first base tried, and the confinement boundary.
            ``None`` drops that base (and is illegal with ``confine``).
        confine: Refuse any file that resolves outside ``project_root``.

    Returns:
        A :class:`SqlFileResolution`; never raises for a bad path.

    Raises:
        ValueError: ``confine`` without a ``project_root`` — there is nothing
            to confine to, and silently not confining is the kind of quiet
            widening this module exists to prevent.
    """
    if confine and project_root is None:
        raise ValueError("resolve_sql_file: confine=True requires a project_root")

    raw_path = Path(raw)
    if raw_path.is_absolute():
        candidates: tuple[Path, ...] = (raw_path,)
    else:
        bases: list[Path] = []
        if project_root is not None:
            bases.append(project_root)
        if migration_file is not None:
            bases.append(migration_file.parent)
        bases.append(Path.cwd())
        # Order-preserving dedupe: cwd == root is the common case and should
        # not be reported as two bases.
        candidates = tuple(dict.fromkeys(base / raw_path for base in bases))

    existing = [c for c in candidates if c.is_file()]
    if not existing:
        return SqlFileResolution(outcome="missing", path=None, tried=candidates)

    if confine:
        assert project_root is not None  # guarded above
        root = project_root.resolve()
        inside = [c for c in existing if c.resolve().is_relative_to(root)]
        if not inside:
            return SqlFileResolution(outcome="escaped", path=None, tried=candidates)
        chosen = inside[0]
    else:
        chosen = existing[0]

    return SqlFileResolution(outcome="found", path=chosen.resolve(), tried=candidates)
