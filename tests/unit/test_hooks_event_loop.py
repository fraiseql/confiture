"""Hooks fire from any context and fail loudly.

``trigger_hook`` used to *skip* every hook when an event loop was already
running, swallow every hook failure into a log line, and leave a closed loop
installed as the current one.
"""

from __future__ import annotations

import asyncio

import pytest

from confiture.core._migrator.engine import Migrator
from confiture.core.hooks import Hook, HookError, HookPhase, HookResult
from confiture.models.migration import Migration
from tests.unit._doubles import connection_double


class _Noop(Migration):
    version = "20260906000008"
    name = "noop"

    def up(self) -> None:
        return None

    def down(self) -> None:
        return None


class _Recording(Hook):
    def __init__(self) -> None:
        super().__init__(hook_id="test.recording", name="recording")
        self.calls = 0

    async def execute(self, context) -> HookResult:
        self.calls += 1
        return HookResult(success=True)


class _Failing(Hook):
    def __init__(self) -> None:
        super().__init__(hook_id="test.failing", name="failing")

    async def execute(self, context) -> HookResult:
        raise RuntimeError("hook exploded")


def _migrator_with(hook: Hook) -> tuple[Migrator, Migration]:
    conn = connection_double()
    migrator = Migrator(connection=conn)
    migrator.register_hook(HookPhase.BEFORE_EXECUTE, hook)
    return migrator, _Noop(connection=conn)


def test_hook_runs_when_an_event_loop_is_already_running() -> None:
    hook = _Recording()
    migrator, migration = _migrator_with(hook)

    async def main() -> None:
        migrator._trigger_hook(HookPhase.BEFORE_EXECUTE, migration)

    asyncio.run(main())
    assert hook.calls == 1


def test_failing_hook_raises_hook_error() -> None:
    migrator, migration = _migrator_with(_Failing())
    with pytest.raises(HookError, match="failing"):
        migrator._trigger_hook(HookPhase.BEFORE_EXECUTE, migration)


def test_no_closed_loop_is_left_as_current() -> None:
    hook = _Recording()
    migrator, migration = _migrator_with(hook)
    prior = asyncio.new_event_loop()
    asyncio.set_event_loop(prior)
    try:
        migrator._trigger_hook(HookPhase.BEFORE_EXECUTE, migration)
        assert hook.calls == 1
        current = asyncio.get_event_loop()
        assert current is prior, "the trigger replaced the caller's event loop"
        assert not current.is_closed()
    finally:
        prior.close()
        asyncio.set_event_loop(None)
