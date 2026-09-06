"""Tests for the ``Captures`` normalization layer (Phase 04, issue #123).

The regex backend produces ``re.Match`` objects with numbered groups
that vary by pattern; the AST backend produces typed pglast nodes.
Templates can't accept either directly — they take a single normalized
:class:`Captures` instance. This test module proves the two dispatchers
produce equivalent captures for equivalent SQL.
"""

from __future__ import annotations

import re

import pytest

from confiture.core.idempotency._captures import (
    Captures,
)
from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.patterns import PATTERN_CATALOG

pglast = pytest.importorskip("pglast")


def _regex_match(pattern: IdempotencyPattern, sql: str) -> re.Match[str]:
    for pdef in PATTERN_CATALOG:
        if pdef.pattern is pattern:
            m = pdef.regex.search(sql)
            assert m is not None, f"regex for {pattern.name} did not match {sql!r}"
            return m
    raise AssertionError(f"no PATTERN entry for {pattern.name}")


def _first_ast_stmt(sql: str):
    tree = pglast.parse_sql(sql)
    return tree[0].stmt


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
