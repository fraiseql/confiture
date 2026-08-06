"""What lock a DDL operation takes, and whether it rewrites the heap (issue #199).

Preflight's only size-awareness used to be ``TableSizeEstimator``'s row-count
hint, surfaced as ``migrate up --batched``. That says nothing about *which* lock a
statement takes or *whether* it rewrites the table — and those two facts, not row
count, are what separate a metadata blip from a multi-minute outage. A
``DROP COLUMN`` on a billion-row table is instant; an ``ALTER COLUMN … TYPE`` on a
small one still rewrites it.

Three properties are deliberate:

* **Pure lookup.** No SQL, no connection, no parser. Preflight is a
  filesystem-only check by design, so the static answer is the primary one and
  anything a database could add is strictly additive.
* **Version-dependent rows are explicit.** Two rows changed with a PostgreSQL
  release — ``ADD COLUMN … DEFAULT`` stopped rewriting in PG 11, and PG 12 can
  prove ``SET NOT NULL`` from a valid ``CHECK`` instead of scanning. Each carries
  :attr:`LockProfile.since_version`, and an unknown server version takes the
  **worse** of the two readings rather than the newer one.
* **Duration is a class, not a number.** ``metadata`` / ``seconds`` /
  ``minutes+``. A predicted duration in seconds is a promise the operator will
  hold confiture to and that no static analysis can keep.

The lock names are PostgreSQL's own, and the table holds for the versions cited
per row (baseline: PostgreSQL 17 documentation, "Explicit Locking" and
"ALTER TABLE").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from confiture.core.replica.classifier import (
    AddColumn,
    AddConstraint,
    AddEnumValue,
    Benign,
    ChangeColumnType,
    CreateIndex,
    CreateTable,
    DdlOperation,
    DropColumn,
    DropObject,
    DropTable,
    RenameColumn,
    RenameObject,
    ReplaceObject,
    Revoke,
    SetNotNull,
    Truncate,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["Duration", "LockLevel", "LockProfile", "lock_profile", "worst_profile"]

# The PostgreSQL release each version-dependent row changed in.
_FAST_DEFAULT_SINCE = 11
_NOT_NULL_FROM_CHECK_SINCE = 12


class LockLevel(Enum):
    """The PostgreSQL table-level lock mode an operation acquires."""

    NONE = "none"
    """Touches no table — a catalog- or type-level change."""

    SHARE_UPDATE_EXCLUSIVE = "share_update_exclusive"
    """Concurrent index builds and ``VACUUM``; blocks neither reads nor writes."""

    SHARE = "share"
    """A plain ``CREATE INDEX``; blocks writes, allows reads."""

    ACCESS_EXCLUSIVE = "access_exclusive"
    """Most ``ALTER TABLE`` forms; blocks everything, including reads."""


class Duration(Enum):
    """How long the lock is plausibly held. A class, never a prediction.

    Ordered least- to most-severe; comparison is the declaration index, so
    ``Duration.METADATA < Duration.MINUTES_PLUS``.
    """

    METADATA = "metadata"
    """A catalog write. Held for microseconds, independent of table size."""

    SECONDS = "seconds"
    """Bounded work — an index-supported check, a small scan."""

    MINUTES_PLUS = "minutes+"
    """A full scan or heap rewrite. Scales with the table."""

    @property
    def severity(self) -> int:
        return _DURATION_SEVERITY[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Duration):
            return NotImplemented
        return self.severity < other.severity

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Duration):
            return NotImplemented
        return self.severity <= other.severity

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Duration):
            return NotImplemented
        return self.severity > other.severity

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Duration):
            return NotImplemented
        return self.severity >= other.severity


_DURATION_SEVERITY: dict[Duration, int] = {d: i for i, d in enumerate(Duration)}


@dataclass(frozen=True)
class LockProfile:
    """What one operation costs in locking terms."""

    lock: LockLevel
    rewrites_table: bool
    blocks_reads: bool
    blocks_writes: bool
    duration: Duration
    since_version: int | None = None
    """The PostgreSQL major this row's *favourable* reading starts at, when the
    answer is version-dependent. ``None`` means the row holds on every version."""

    note: str | None = None
    """One line naming the caveat, when a row has one."""


# The conservative answer for an operation with no row: assume the worst. An
# operation confiture cannot cost must not read as cheap — that is #206's lesson
# applied to this table.
_UNKNOWN = LockProfile(
    lock=LockLevel.ACCESS_EXCLUSIVE,
    rewrites_table=True,
    blocks_reads=True,
    blocks_writes=True,
    duration=Duration.MINUTES_PLUS,
    note="operation not in the lock table; assumed to be the worst case",
)

# A brief catalog-only ALTER TABLE: ACCESS EXCLUSIVE, but held for microseconds.
_METADATA_ALTER = LockProfile(
    lock=LockLevel.ACCESS_EXCLUSIVE,
    rewrites_table=False,
    blocks_reads=True,
    blocks_writes=True,
    duration=Duration.METADATA,
)

# Touches no table at all.
_NO_LOCK = LockProfile(
    lock=LockLevel.NONE,
    rewrites_table=False,
    blocks_reads=False,
    blocks_writes=False,
    duration=Duration.METADATA,
)


def lock_profile(op: DdlOperation, *, server_version: int | None = None) -> LockProfile:
    """The lock and rewrite cost of ``op``.

    ``server_version`` is the PostgreSQL **major** (``16``, not ``160004``). When
    it is ``None`` — the filesystem-only default — every version-dependent row
    answers with its pre-improvement reading.
    """
    if isinstance(op, AddColumn):
        return _add_column(op, server_version)
    if isinstance(op, SetNotNull):
        return _set_not_null(server_version)
    if isinstance(op, ChangeColumnType):
        return LockProfile(
            lock=LockLevel.ACCESS_EXCLUSIVE,
            rewrites_table=True,
            blocks_reads=True,
            blocks_writes=True,
            duration=Duration.MINUTES_PLUS,
            note="rewrites the heap and every index on the column",
        )
    if isinstance(op, AddConstraint):
        if op.not_valid:
            return _METADATA_ALTER
        return LockProfile(
            lock=LockLevel.ACCESS_EXCLUSIVE,
            rewrites_table=False,
            blocks_reads=True,
            blocks_writes=True,
            duration=Duration.MINUTES_PLUS,
            note="validates against every existing row; ADD … NOT VALID defers the scan",
        )
    if isinstance(op, CreateIndex):
        if op.concurrently:
            return LockProfile(
                lock=LockLevel.SHARE_UPDATE_EXCLUSIVE,
                rewrites_table=False,
                blocks_reads=False,
                blocks_writes=False,
                duration=Duration.MINUTES_PLUS,
                note="online, but takes two table scans and cannot run in a transaction",
            )
        return LockProfile(
            lock=LockLevel.SHARE,
            rewrites_table=False,
            blocks_reads=False,
            blocks_writes=True,
            duration=Duration.MINUTES_PLUS,
            note="blocks writes for the whole build; use CONCURRENTLY on a hot table",
        )
    if isinstance(op, (DropColumn, RenameColumn, RenameObject, DropTable, Truncate)):
        # All catalog-only. DROP COLUMN marks the attribute dropped rather than
        # rewriting; TRUNCATE swaps in a new heap file.
        return _METADATA_ALTER
    if isinstance(op, (CreateTable, AddEnumValue, Revoke, DropObject, ReplaceObject)):
        return _NO_LOCK
    if isinstance(op, Benign):
        return _BENIGN_PROFILES.get(op.kind or "", _NO_LOCK)
    return _UNKNOWN


def _add_column(op: AddColumn, server_version: int | None) -> LockProfile:
    """`ADD COLUMN` is metadata-only, except for a pre-PG-11 non-null default."""
    if not op.has_default:
        return _METADATA_ALTER
    if server_version is not None and server_version >= _FAST_DEFAULT_SINCE:
        return LockProfile(
            lock=LockLevel.ACCESS_EXCLUSIVE,
            rewrites_table=False,
            blocks_reads=True,
            blocks_writes=True,
            duration=Duration.METADATA,
            since_version=_FAST_DEFAULT_SINCE,
            note="PostgreSQL 11+ stores the default in the catalog instead of rewriting",
        )
    return LockProfile(
        lock=LockLevel.ACCESS_EXCLUSIVE,
        rewrites_table=True,
        blocks_reads=True,
        blocks_writes=True,
        duration=Duration.MINUTES_PLUS,
        since_version=_FAST_DEFAULT_SINCE,
        note=(
            "rewrites the whole table below PostgreSQL 11; the server version is "
            "unknown here, so the older reading stands"
            if server_version is None
            else "rewrites the whole table below PostgreSQL 11"
        ),
    )


def _set_not_null(server_version: int | None) -> LockProfile:
    """`SET NOT NULL` scans, unless PG 12+ can prove it from a valid CHECK."""
    if server_version is not None and server_version >= _NOT_NULL_FROM_CHECK_SINCE:
        return LockProfile(
            lock=LockLevel.ACCESS_EXCLUSIVE,
            rewrites_table=False,
            blocks_reads=True,
            blocks_writes=True,
            duration=Duration.SECONDS,
            since_version=_NOT_NULL_FROM_CHECK_SINCE,
            note=(
                "PostgreSQL 12+ skips the scan when a valid CHECK (col IS NOT NULL) "
                "already exists; without one it still scans"
            ),
        )
    return LockProfile(
        lock=LockLevel.ACCESS_EXCLUSIVE,
        rewrites_table=False,
        blocks_reads=True,
        blocks_writes=True,
        duration=Duration.MINUTES_PLUS,
        since_version=_NOT_NULL_FROM_CHECK_SINCE,
        note="scans every row to prove no NULL is present",
    )


# `Benign` carries a kind rather than a class, so its costs live in one table.
_BENIGN_PROFILES: dict[str, LockProfile] = {
    "drop_index": _METADATA_ALTER,
    "drop_trigger": _METADATA_ALTER,
    "drop_policy": _METADATA_ALTER,
    "drop_rule": _METADATA_ALTER,
    "drop_constraint": _METADATA_ALTER,
    "drop_not_null": _METADATA_ALTER,
    "column_default": _METADATA_ALTER,
    "change_owner": _METADATA_ALTER,
    "create_table": _NO_LOCK,
    "cluster": LockProfile(
        lock=LockLevel.ACCESS_EXCLUSIVE,
        rewrites_table=True,
        blocks_reads=True,
        blocks_writes=True,
        duration=Duration.MINUTES_PLUS,
        note="rewrites the table in index order",
    ),
    "reindex": LockProfile(
        lock=LockLevel.ACCESS_EXCLUSIVE,
        rewrites_table=False,
        blocks_reads=True,
        blocks_writes=True,
        duration=Duration.MINUTES_PLUS,
        note="REINDEX CONCURRENTLY avoids the exclusive lock",
    ),
    "refresh_materialized_view": LockProfile(
        lock=LockLevel.ACCESS_EXCLUSIVE,
        rewrites_table=True,
        blocks_reads=True,
        blocks_writes=True,
        duration=Duration.MINUTES_PLUS,
        note="REFRESH … CONCURRENTLY keeps the view readable, but needs a unique index",
    ),
    "insert": LockProfile(
        lock=LockLevel.SHARE_UPDATE_EXCLUSIVE,
        rewrites_table=False,
        blocks_reads=False,
        blocks_writes=False,
        duration=Duration.SECONDS,
    ),
    "update": LockProfile(
        lock=LockLevel.SHARE_UPDATE_EXCLUSIVE,
        rewrites_table=False,
        blocks_reads=False,
        blocks_writes=False,
        duration=Duration.MINUTES_PLUS,
        note="row locks scale with the number of rows matched",
    ),
    "delete": LockProfile(
        lock=LockLevel.SHARE_UPDATE_EXCLUSIVE,
        rewrites_table=False,
        blocks_reads=False,
        blocks_writes=False,
        duration=Duration.MINUTES_PLUS,
        note="row locks scale with the number of rows matched",
    ),
}


def worst_profile(profiles: Iterable[LockProfile]) -> LockProfile | None:
    """The most expensive profile in ``profiles`` — the one that decides a window.

    Ranked by duration first, then by whether the operation rewrites the heap.
    Returns ``None`` for an empty set.
    """
    ranked = sorted(
        profiles,
        key=lambda p: (p.duration.severity, p.rewrites_table, p.blocks_reads, p.blocks_writes),
    )
    return ranked[-1] if ranked else None
