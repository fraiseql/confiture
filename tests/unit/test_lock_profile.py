"""Operation → lock level and rewrite cost (issue #199).

The lock a statement takes and whether it rewrites the heap are properties of the
*operation class*, largely independent of table size, and they are what separate a
metadata blip from a multi-minute outage. Two rows are version-dependent and must
answer conservatively when the server version is unknown.
"""

from __future__ import annotations

import pytest

from confiture.core.lock_profile import Duration, LockLevel, lock_profile
from confiture.core.replica.classifier import (
    AddColumn,
    AddConstraint,
    AddEnumValue,
    ChangeColumnType,
    CreateIndex,
    CreateTable,
    DropColumn,
    DropTable,
    Other,
    RenameColumn,
    SetNotNull,
    Truncate,
)


def test_add_column_nullable_is_metadata_only() -> None:
    profile = lock_profile(AddColumn(table="t", column="c", nullable=True))
    assert profile.rewrites_table is False
    assert profile.duration is Duration.METADATA
    assert profile.lock is LockLevel.ACCESS_EXCLUSIVE


def test_create_index_blocks_writes_but_not_reads() -> None:
    profile = lock_profile(CreateIndex(table="t", concurrently=False))
    assert profile.blocks_writes is True
    assert profile.blocks_reads is False
    assert profile.lock is LockLevel.SHARE


def test_create_index_concurrently_blocks_neither() -> None:
    profile = lock_profile(CreateIndex(table="t", concurrently=True))
    assert profile.blocks_writes is False
    assert profile.blocks_reads is False
    assert profile.lock is LockLevel.SHARE_UPDATE_EXCLUSIVE


def test_alter_column_type_rewrites() -> None:
    profile = lock_profile(ChangeColumnType(table="t", column="c"))
    assert profile.rewrites_table is True
    assert profile.duration is Duration.MINUTES_PLUS


def test_add_enum_value_takes_no_table_lock() -> None:
    """`ALTER TYPE … ADD VALUE` touches the type catalog, not the heap."""
    profile = lock_profile(AddEnumValue(table="mood", value="ok"))
    assert profile.rewrites_table is False
    assert profile.blocks_reads is False
    assert profile.blocks_writes is False
    assert profile.duration is Duration.METADATA


@pytest.mark.parametrize(
    ("op", "rewrites"),
    [
        (DropColumn(table="t", column="c"), False),
        (RenameColumn(table="t", old="a", new="b"), False),
        (DropTable(table="t"), False),
        (Truncate(table="t"), False),
        (CreateTable(table="t"), False),
        (ChangeColumnType(table="t", column="c"), True),
    ],
)
def test_rewrite_flags(op, rewrites: bool) -> None:
    assert lock_profile(op).rewrites_table is rewrites


# --------------------------------------------------------------------------- #
# Version-dependent rows
# --------------------------------------------------------------------------- #


def test_add_column_default_rewrites_below_pg11() -> None:
    op = AddColumn(table="t", column="c", nullable=False, has_default=True)
    assert lock_profile(op, server_version=10).rewrites_table is True
    assert lock_profile(op, server_version=10).duration is Duration.MINUTES_PLUS


def test_add_column_default_does_not_rewrite_from_pg11() -> None:
    """PG 11's fast default turns the rewrite into a catalog write."""
    op = AddColumn(table="t", column="c", nullable=False, has_default=True)
    profile = lock_profile(op, server_version=11)
    assert profile.rewrites_table is False
    assert profile.duration is Duration.METADATA


def test_unknown_version_answers_conservatively() -> None:
    """No connection ⇒ assume the worse of the two readings."""
    op = AddColumn(table="t", column="c", nullable=False, has_default=True)
    unknown = lock_profile(op)
    assert unknown.rewrites_table is True
    assert unknown == lock_profile(op, server_version=None)
    assert unknown.since_version == 11


def test_set_not_null_scans_below_pg12() -> None:
    profile = lock_profile(SetNotNull(table="t", column="c"), server_version=11)
    assert profile.duration is Duration.MINUTES_PLUS
    assert profile.blocks_reads is True


def test_set_not_null_can_skip_the_scan_from_pg12() -> None:
    """PG 12 can prove NOT NULL from a valid CHECK instead of scanning."""
    profile = lock_profile(SetNotNull(table="t", column="c"), server_version=12)
    assert profile.duration is Duration.SECONDS
    assert profile.note


def test_add_constraint_not_valid_defers_the_scan() -> None:
    immediate = lock_profile(AddConstraint(table="t", kind="check", not_valid=False))
    deferred = lock_profile(AddConstraint(table="t", kind="check", not_valid=True))
    assert immediate.duration is Duration.MINUTES_PLUS
    assert deferred.duration is Duration.METADATA


# --------------------------------------------------------------------------- #
# Totality
# --------------------------------------------------------------------------- #


def test_unclassified_operation_gets_the_conservative_profile() -> None:
    """An operation with no row must not read as cheap (the #206 lesson)."""
    profile = lock_profile(Other(reason="dynamic sql"))
    assert profile.rewrites_table is True
    assert profile.blocks_reads is True
    assert profile.blocks_writes is True
    assert profile.duration is Duration.MINUTES_PLUS


def test_every_operation_class_has_a_profile() -> None:
    """Totality guard: a new DdlOperation subclass must not fall off the table."""
    import inspect

    from confiture.core.replica import classifier as mod
    from confiture.core.replica.classifier import DdlOperation

    subclasses = [
        obj
        for _name, obj in inspect.getmembers(mod, inspect.isclass)
        if issubclass(obj, DdlOperation) and obj is not DdlOperation
    ]
    assert subclasses
    for cls in subclasses:
        assert lock_profile(cls()) is not None, cls.__name__


def test_duration_orders_metadata_below_minutes() -> None:
    assert Duration.METADATA < Duration.SECONDS < Duration.MINUTES_PLUS
