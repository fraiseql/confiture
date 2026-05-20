"""Helpers for ``confiture migrate baseline --from-db`` — Issue #119.

The flow:

1. Connect to a source database.
2. Read its ``tb_confiture`` rows.
3. Filter to the intersection of source-applied versions and locally
   present migration files.
4. Optionally cap at ``--through <version>``.
5. Insert the surviving rows into the target's tracking table.

This module owns the pure parts of that flow (row selection, warning
generation).  The IO parts (opening the source connection, executing
INSERTs against the target) live on :class:`Migrator.baseline_from_db`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from confiture.exceptions import ConfigurationError


@dataclass(frozen=True)
class BaselineCopySelection:
    """The output of :func:`_select_rows_to_copy`.

    Attributes:
        rows: Source rows that should be copied into the target's
            tracking table, in source order.
        source_only: Versions applied on source but missing from local
            migration files — *not* copied, surfaced as warnings.
        warnings: Human-readable diagnostics to print to the operator
            before proceeding.  Empty when nothing notable happened.
    """

    rows: list[dict[str, Any]] = field(default_factory=list)
    source_only: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _select_rows_to_copy(
    source_rows: list[dict[str, Any]],
    *,
    local_versions: set[str],
    through: str | None = None,
) -> BaselineCopySelection:
    """Decide which source rows to copy.

    Args:
        source_rows: The full row set from the source DB's tb_confiture,
            ordered by ``version`` ascending.  Each row must carry at
            least a ``version`` key.
        local_versions: Set of version strings present in the operator's
            local ``db/migrations/`` directory.
        through: Optional version string; when set, source rows with a
            version above this are excluded from the copy.

    Returns:
        :class:`BaselineCopySelection` — rows to copy plus diagnostics.

    Raises:
        ConfigurationError: If *through* is set but does not match any
            version in either the source rows or the local files.  The
            operator named a checkpoint that doesn't exist; refuse to
            proceed silently.
    """
    source_versions = {r["version"] for r in source_rows}

    if through is not None and through not in source_versions and through not in local_versions:
        raise ConfigurationError(
            f"--through version {through!r} not found in source DB or local migrations.  "
            "Either the source is missing the checkpoint, or the operator named a version "
            "that does not exist."
        )

    rows: list[dict[str, Any]] = []
    source_only: list[str] = []
    capped_versions: list[str] = []

    for row in source_rows:
        version = row["version"]
        # Cap test runs first so versions above the cap are not reported as
        # source-only when the operator deliberately excluded them.
        if through is not None and _version_above(version, through):
            capped_versions.append(version)
            continue
        if version not in local_versions:
            source_only.append(version)
            continue
        rows.append(row)

    warnings: list[str] = []
    if source_only:
        warnings.append(
            f"Source DB has {len(source_only)} version(s) not present in local migrations: "
            f"{', '.join(source_only)}.  These rows will NOT be copied.  "
            "Either pull the missing migration files into db/migrations/, or accept "
            "that the target will treat those versions as pending."
        )
    if capped_versions:
        warnings.append(
            f"--through {through!r} excludes {len(capped_versions)} version(s) "
            f"that source DB has applied: {', '.join(capped_versions)}.  "
            "Source is ahead of the cap."
        )

    return BaselineCopySelection(rows=rows, source_only=source_only, warnings=warnings)


def _version_above(candidate: str, through: str) -> bool:
    """Return True when *candidate* is strictly above *through* in version order.

    Confiture supports both numeric/zero-padded prefixes (``001``, ``002``)
    and timestamp prefixes (``YYYYMMDDHHMMSS``).  Lex comparison is correct
    *within* a single format (``001 < 002`` and ``20260101000000 <
    20260102000000`` both order as expected).

    Mixing pad widths within the same database (e.g. source has ``0042``
    while local files have ``42``) is not handled here — those rows are
    caught upstream by the ``local_versions`` set-membership check in
    :func:`_select_rows_to_copy` and surface as ``source_only`` warnings,
    not silent miscompares.
    """
    return candidate > through
