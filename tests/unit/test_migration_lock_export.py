"""Tests for MigrationLock and LockConfig public exports (issue #91)."""

import confiture


def test_migration_lock_importable_from_top_level():
    """MigrationLock is importable from the confiture package."""
    from confiture import MigrationLock

    assert MigrationLock is not None


def test_lock_config_importable_from_top_level():
    """LockConfig is importable from the confiture package."""
    from confiture import LockConfig

    assert LockConfig is not None


def test_migration_lock_in_all():
    """MigrationLock is listed in __all__."""
    assert "MigrationLock" in confiture.__all__


def test_lock_config_in_all():
    """LockConfig is listed in __all__."""
    assert "LockConfig" in confiture.__all__
