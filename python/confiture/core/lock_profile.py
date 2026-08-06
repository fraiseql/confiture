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

__all__ = [
    "FAST_DEFAULT_SINCE",
    "NOT_NULL_FROM_CHECK_SINCE",
    "Duration",
    "LockLevel",
    "LockProfile",
    "lock_profile",
    "profile_for_kind",
    "worst_profile",
]

# The PostgreSQL release each version-dependent row changed in.
FAST_DEFAULT_SINCE = 11
NOT_NULL_FROM_CHECK_SINCE = 12


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


def profile_for_kind(
    kind: str | None,
    *,
    has_default: bool = False,
    nullable: bool = True,
    concurrently: bool = False,
    not_valid: bool = False,
    rewrites: bool | None = None,
    server_version: int | None = None,
) -> LockProfile:
    """The lock and rewrite cost of a change of ``kind``.

    ``kind`` is the vocabulary ``core/change_set.py`` emits, which is also what
    crosses the adapter seam. :func:`lock_profile` is the twin keyed on a typed
    :class:`~confiture.core.replica.classifier.DdlOperation`; both read this one
    table, so the two surfaces cannot disagree about what an operation costs.

    ``server_version`` is the PostgreSQL **major** (``16``, not ``160004``). When
    it is ``None`` — the filesystem-only default — every version-dependent row
    answers with its pre-improvement reading. ``rewrites`` overrides the heap
    verdict for ``alter_column_type``, where only the type lattice knows.
    """
    if kind == "add_column":
        return _add_column(
            has_default=has_default, nullable=nullable, server_version=server_version
        )
    if kind == "set_not_null":
        return _set_not_null(server_version)
    if kind == "alter_column_type":
        return _alter_column_type(rewrites)
    if kind == "add_constraint":
        if not_valid:
            return _METADATA_ALTER
        return LockProfile(
            lock=LockLevel.ACCESS_EXCLUSIVE,
            rewrites_table=False,
            blocks_reads=True,
            blocks_writes=True,
            duration=Duration.MINUTES_PLUS,
            note="validates against every existing row; ADD … NOT VALID defers the scan",
        )
    if kind == "create_index":
        if concurrently:
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
    profile = _PROFILE_BY_KIND.get(kind or "")
    if profile is not None:
        return profile
    if kind and kind.startswith("create_"):
        return _NO_LOCK
    return _UNKNOWN


def _alter_column_type(rewrites: bool | None) -> LockProfile:
    """A type change rewrites unless the lattice proves the coercion is binary."""
    if rewrites is False:
        return LockProfile(
            lock=LockLevel.ACCESS_EXCLUSIVE,
            rewrites_table=False,
            blocks_reads=True,
            blocks_writes=True,
            duration=Duration.METADATA,
            note="binary-coercible: PostgreSQL updates the catalog without a rewrite",
        )
    return LockProfile(
        lock=LockLevel.ACCESS_EXCLUSIVE,
        rewrites_table=True,
        blocks_reads=True,
        blocks_writes=True,
        duration=Duration.MINUTES_PLUS,
        note="rewrites the heap and every index on the column",
    )


# Kinds whose cost depends on nothing but the kind itself.
_PROFILE_BY_KIND: dict[str, LockProfile] = {
    # Catalog-only ALTER TABLE forms. DROP COLUMN marks the attribute dropped
    # rather than rewriting; TRUNCATE swaps in a new heap file.
    "drop_column": _METADATA_ALTER,
    "rename_column": _METADATA_ALTER,
    "rename_object": _METADATA_ALTER,
    "drop_table": _METADATA_ALTER,
    "truncate": _METADATA_ALTER,
    "drop_constraint": _METADATA_ALTER,
    "set_column_default": _METADATA_ALTER,
    "drop_column_default": _METADATA_ALTER,
    "column_default": _METADATA_ALTER,
    "drop_not_null": _METADATA_ALTER,
    "change_owner": _METADATA_ALTER,
    "drop_index": _METADATA_ALTER,
    "drop_trigger": _METADATA_ALTER,
    "drop_policy": _METADATA_ALTER,
    "drop_rule": _METADATA_ALTER,
    # Objects whose removal or replacement touches no heap.
    "drop_view": _NO_LOCK,
    "drop_materialized_view": _NO_LOCK,
    "drop_sequence": _NO_LOCK,
    "drop_schema": _NO_LOCK,
    "drop_type": _NO_LOCK,
    "drop_domain": _NO_LOCK,
    "drop_function": _NO_LOCK,
    "drop_procedure": _NO_LOCK,
    "drop_extension": _NO_LOCK,
    "replace_view": _NO_LOCK,
    "replace_function": _NO_LOCK,
    "replace_procedure": _NO_LOCK,
    "grant": _NO_LOCK,
    "revoke": _NO_LOCK,
    "comment": _NO_LOCK,
    "select": _NO_LOCK,
    "alter_type": _NO_LOCK,
    "alter_sequence": _NO_LOCK,
    "alter_default_privileges": _NO_LOCK,
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

# DdlOperation class → the kind naming the same change. The typed classifier and
# the change-set vocabulary meet here and nowhere else.
_KIND_BY_OP: dict[type[DdlOperation], str] = {
    AddColumn: "add_column",
    DropColumn: "drop_column",
    RenameColumn: "rename_column",
    RenameObject: "rename_object",
    ChangeColumnType: "alter_column_type",
    AddConstraint: "add_constraint",
    CreateIndex: "create_index",
    CreateTable: "create_table",
    DropTable: "drop_table",
    Truncate: "truncate",
    Revoke: "revoke",
    SetNotNull: "set_not_null",
    AddEnumValue: "alter_type",
}


def lock_profile(op: DdlOperation, *, server_version: int | None = None) -> LockProfile:
    """The lock and rewrite cost of a typed operation. See :func:`profile_for_kind`."""
    if isinstance(op, Benign):
        return profile_for_kind(op.kind, server_version=server_version)
    if isinstance(op, (DropObject, ReplaceObject)):
        return _NO_LOCK
    kind = _KIND_BY_OP.get(type(op))
    if kind is None:
        return _UNKNOWN
    return profile_for_kind(
        kind,
        has_default=getattr(op, "has_default", False),
        nullable=getattr(op, "nullable", True),
        concurrently=getattr(op, "concurrently", False),
        not_valid=getattr(op, "not_valid", False),
        server_version=server_version,
    )


def _add_column(*, has_default: bool, nullable: bool, server_version: int | None) -> LockProfile:
    """`ADD COLUMN` is metadata-only, except for a pre-PG-11 non-null default."""
    del nullable  # named for the call sites; both NOT NULL forms cost the same
    if not has_default:
        return _METADATA_ALTER
    if server_version is not None and server_version >= FAST_DEFAULT_SINCE:
        return LockProfile(
            lock=LockLevel.ACCESS_EXCLUSIVE,
            rewrites_table=False,
            blocks_reads=True,
            blocks_writes=True,
            duration=Duration.METADATA,
            since_version=FAST_DEFAULT_SINCE,
            note="PostgreSQL 11+ stores the default in the catalog instead of rewriting",
        )
    return LockProfile(
        lock=LockLevel.ACCESS_EXCLUSIVE,
        rewrites_table=True,
        blocks_reads=True,
        blocks_writes=True,
        duration=Duration.MINUTES_PLUS,
        since_version=FAST_DEFAULT_SINCE,
        note=(
            "rewrites the whole table below PostgreSQL 11; the server version is "
            "unknown here, so the older reading stands"
            if server_version is None
            else "rewrites the whole table below PostgreSQL 11"
        ),
    )


def _set_not_null(server_version: int | None) -> LockProfile:
    """`SET NOT NULL` scans, unless PG 12+ can prove it from a valid CHECK."""
    if server_version is not None and server_version >= NOT_NULL_FROM_CHECK_SINCE:
        return LockProfile(
            lock=LockLevel.ACCESS_EXCLUSIVE,
            rewrites_table=False,
            blocks_reads=True,
            blocks_writes=True,
            duration=Duration.SECONDS,
            since_version=NOT_NULL_FROM_CHECK_SINCE,
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
        since_version=NOT_NULL_FROM_CHECK_SINCE,
        note="scans every row to prove no NULL is present",
    )


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
