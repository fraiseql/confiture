"""Tests for the ``Captures`` normalization layer.

Templates never read a pglast node: they take one normalized :class:`Captures`
instance, which defaults to all-None and is frozen.
"""

from __future__ import annotations

import pytest

from confiture.core.idempotency._captures import (
    Captures,
)


class TestCapturesDataclass:
    """Captures defaults to all-None and is hashable/frozen."""

    def test_default_all_none(self) -> None:
        cap = Captures()
        assert cap.schema is None
        assert cap.table is None
        assert cap.column is None
        assert cap.new_column is None
        assert cap.constraint is None
        assert cap.type_name is None
        assert cap.index_name is None
        assert cap.view is None
        assert cap.sequence is None
        assert cap.extension is None

    def test_frozen(self) -> None:
        cap = Captures(table="orders")
        with pytest.raises((AttributeError, TypeError)):
            cap.table = "users"  # type: ignore[misc]
