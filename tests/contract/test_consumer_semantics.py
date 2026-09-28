"""Contract test pinning what the properties a consumer reads *answer*.

``test_consumer_symbols.py`` pins that each member a consumer reads still
resolves, and that each call shape has not narrowed. A property can keep its
name, its signature and its return type and still change its answer: in 1.24.0
``MigrateUpResult.has_errors`` went from ``not success and len(errors) > 0`` to
``not success``, the symbol probe stayed green, and fraisier learned of it from
its own test failing after the release (#508).

So each property here is pinned by its truth table: a handful of results a
consumer actually receives, and what the property says about each. Changing a
row changes what a consumer's branch does. That is a decision to make in the
open, with the consumer named, never a refactor that goes green.

Every property named in ``test_consumer_symbols.MEMBERS`` must have a row
(``test_every_property_a_consumer_reads_has_a_truth_table``), so the gap cannot
reopen when a consumer starts reading a new one. Properties nobody reads yet may
be pinned too; ``has_errors`` and ``halted`` are, because they are the shapes
#508 is about.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from typing import Any, NamedTuple

import pytest
from tests.contract.test_consumer_symbols import MEMBERS

from confiture.models.results import (
    MigrateUpResult,
    MigrationApplied,
    MigrationInfo,
    SkippedMigration,
    StatusResult,
)


class Row(NamedTuple):
    """One property of one result, and what it answers."""

    target: str
    """``module:Class.property``, as ``MEMBERS`` spells the class."""
    case: str
    result: Callable[[], Any]
    expected: Any


# ---------------------------------------------------------------------------
# The results a consumer receives
# ---------------------------------------------------------------------------


def _applied(version: str = "001") -> MigrationApplied:
    return MigrationApplied(version=version, name="init", duration_ms=1, rows_affected=0)


def _up_succeeded() -> MigrateUpResult:
    return MigrateUpResult(success=True, migrations_applied=[_applied()], total_duration_ms=1)


def _up_nothing_to_do() -> MigrateUpResult:
    return MigrateUpResult(success=True, migrations_applied=[], total_duration_ms=0)


def _up_failed() -> MigrateUpResult:
    return MigrateUpResult(
        success=False,
        migrations_applied=[],
        total_duration_ms=1,
        errors=["Migration 002 failed: relation already exists"],
    )


def _up_halted() -> MigrateUpResult:
    """A run that stopped at a ``requires_superuser`` migration (#137)."""
    return MigrateUpResult(
        success=False,
        migrations_applied=[_applied()],
        total_duration_ms=1,
        errors=["Migration 002 requires a superuser: run `confiture migrate apply-as`"],
        skipped_superuser=[
            SkippedMigration(version="002", name="ext", reason="requires_superuser")
        ],
        pending=["003"],
    )


def _status(*statuses: str) -> StatusResult:
    migrations = [
        MigrationInfo(version=f"{i:03d}", name=f"m{i}", status=status)
        for i, status in enumerate(statuses, start=1)
    ]
    return StatusResult(
        migrations=migrations,
        tracking_table_exists=True,
        tracking_table="tb_confiture",
        summary={},
    )


_UP = "confiture:MigrateUpResult"
_STATUS = "confiture.models.results:StatusResult"

TRUTH: tuple[Row, ...] = (
    # has_errors: "the run did not succeed" since 1.24.0 — a halted run has errors.
    Row(f"{_UP}.has_errors", "succeeded", _up_succeeded, False),
    Row(f"{_UP}.has_errors", "nothing to do", _up_nothing_to_do, False),
    Row(f"{_UP}.has_errors", "failed", _up_failed, True),
    Row(f"{_UP}.has_errors", "halted", _up_halted, True),
    # halted: only the requires_superuser stop, never a failure.
    Row(f"{_UP}.halted", "succeeded", _up_succeeded, False),
    Row(f"{_UP}.halted", "failed", _up_failed, False),
    Row(f"{_UP}.halted", "halted", _up_halted, True),
    # error_summary: fraisier logs it (`_incomplete_reason`).
    Row(f"{_UP}.error_summary", "succeeded", _up_succeeded, None),
    Row(
        f"{_UP}.error_summary",
        "failed",
        _up_failed,
        "Migration 002 failed: relation already exists",
    ),
    Row(
        f"{_UP}.error_summary",
        "halted",
        _up_halted,
        "Migration 002 requires a superuser: run `confiture migrate apply-as`",
    ),
    # StatusResult: fraisier decides whether to migrate on has_pending.
    Row(f"{_STATUS}.has_pending", "empty", _status, False),
    Row(f"{_STATUS}.has_pending", "all applied", lambda: _status("applied"), False),
    Row(f"{_STATUS}.has_pending", "one pending", lambda: _status("applied", "pending"), True),
    Row(f"{_STATUS}.has_pending", "unknown is not pending", lambda: _status("unknown"), False),
    Row(f"{_STATUS}.pending", "mixed", lambda: _status("applied", "pending", "unknown"), ["002"]),
    Row(f"{_STATUS}.applied", "mixed", lambda: _status("applied", "pending", "unknown"), ["001"]),
)


@pytest.mark.parametrize("row", TRUTH, ids=lambda r: f"{r.target.split(':')[1]}[{r.case}]")
def test_a_property_answers_what_its_consumers_branch_on(row: Row) -> None:
    prop = row.target.rsplit(".", 1)[1]
    assert getattr(row.result(), prop) == row.expected, (
        f"{row.target} changed its answer for a {row.case!r} result. A consumer "
        f"branches on it: changing this row is a breaking change to announce."
    )


def _consumer_read_properties() -> set[str]:
    found: set[str] = set()
    for members in MEMBERS:
        module, attribute = members.target.split(":")
        cls = getattr(importlib.import_module(module), attribute)
        for name in members.names:
            if isinstance(inspect.getattr_static(cls, name, None), property):
                found.add(f"{members.target}.{name}")
    return found


def test_the_member_walk_still_finds_properties() -> None:
    """A floor: if this is empty, the walk stopped seeing properties."""
    assert f"{_STATUS}.has_pending" in _consumer_read_properties()


def test_every_property_a_consumer_reads_has_a_truth_table() -> None:
    pinned = {row.target for row in TRUTH}
    assert sorted(_consumer_read_properties() - pinned) == []
