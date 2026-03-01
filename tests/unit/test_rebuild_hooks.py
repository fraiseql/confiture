"""Tests for Phase 4: Hooks integration (BEFORE/AFTER_REBUILD)."""

from __future__ import annotations


class TestRebuildHookPhases:
    """Cycle 4.1: Hook phases and context."""

    def test_before_rebuild_phase(self):
        from confiture.core.hooks.phases import HookPhase

        assert HookPhase.BEFORE_REBUILD.value == "before_rebuild"

    def test_after_rebuild_phase(self):
        from confiture.core.hooks.phases import HookPhase

        assert HookPhase.AFTER_REBUILD.value == "after_rebuild"

    def test_rebuild_context_fields(self):
        from confiture.core.hooks.context import RebuildContext

        ctx = RebuildContext(
            env="staging",
            drop_schemas=True,
            migrations_count=10,
            schemas_dropped=["public", "myapp"],
        )
        assert ctx.env == "staging"
        assert ctx.drop_schemas is True
        assert ctx.migrations_count == 10
        assert ctx.schemas_dropped == ["public", "myapp"]

    def test_rebuild_context_defaults(self):
        from confiture.core.hooks.context import RebuildContext

        ctx = RebuildContext(
            env="local",
            drop_schemas=False,
            migrations_count=0,
            schemas_dropped=[],
        )
        assert ctx.metadata == {}
