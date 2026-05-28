"""Unit tests for ``requires_superuser`` on Migration (issue #137 part 2).

Declarative attribute that lets a migration opt out of the ordinary
`migrate up` chain. When True, `MigratorSession.up()` halts at the
first such migration with an exit-1 result and a recovery hint
pointing to `confiture migrate apply-as`.

Mirrors the existing ``transactional: bool = True`` instance-attribute
pattern at python/confiture/models/migration.py:142.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import psycopg

from confiture.models.migration import Migration


def test_requires_superuser_defaults_false() -> None:
    """A vanilla migration defaults to `requires_superuser = False`."""

    class _M(Migration):
        version = "20260528120000"
        name = "vanilla"

        def up(self) -> None:
            pass

        def down(self) -> None:
            pass

    conn: psycopg.Connection = MagicMock()
    inst = _M(connection=conn)
    assert inst.requires_superuser is False


def test_subclass_can_override_requires_superuser_true() -> None:
    """A subclass that sets `requires_superuser = True` is recognized."""

    class _M(Migration):
        version = "20260528120100"
        name = "needs_superuser"
        requires_superuser = True

        def up(self) -> None:
            pass

        def down(self) -> None:
            pass

    conn: psycopg.Connection = MagicMock()
    inst = _M(connection=conn)
    assert inst.requires_superuser is True


def test_requires_superuser_lives_alongside_transactional() -> None:
    """Both attributes coexist on the same class; neither shadows the other."""

    class _M(Migration):
        version = "20260528120200"
        name = "both"
        transactional = False
        requires_superuser = True

        def up(self) -> None:
            pass

        def down(self) -> None:
            pass

    conn: psycopg.Connection = MagicMock()
    inst = _M(connection=conn)
    assert inst.transactional is False
    assert inst.requires_superuser is True
