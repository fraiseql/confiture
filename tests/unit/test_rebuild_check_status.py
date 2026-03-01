"""Tests for Phase 6: Status integration (--check-rebuild)."""

from __future__ import annotations

from confiture.models.results import MigrationInfo, StatusResult


class TestStatusResultRebuildFields:
    """Cycle 6.1: rebuild_recommended on StatusResult."""

    def test_default_rebuild_recommended_false(self):
        result = StatusResult(
            migrations=[],
            tracking_table_exists=True,
            tracking_table="tb_confiture",
            summary={"applied": 0, "pending": 0, "total": 0},
        )
        assert result.rebuild_recommended is False
        assert result.rebuild_reasons == []

    def test_rebuild_recommended_serialized(self):
        result = StatusResult(
            migrations=[],
            tracking_table_exists=True,
            tracking_table="tb_confiture",
            summary={"applied": 0, "pending": 0, "total": 0},
            rebuild_recommended=True,
            rebuild_reasons=["6 pending migrations exceed threshold of 5"],
        )
        d = result.to_dict()
        assert d["rebuild_recommended"] is True
        assert len(d["rebuild_reasons"]) == 1

    def test_backward_compatible_creation(self):
        """Existing code that doesn't pass rebuild_recommended still works."""
        result = StatusResult(
            migrations=[
                MigrationInfo(version="001", name="init", status="applied"),
            ],
            tracking_table_exists=True,
            tracking_table="tb_confiture",
            summary={"applied": 1, "pending": 0, "total": 1},
        )
        assert result.rebuild_recommended is False
        d = result.to_dict()
        assert "rebuild_recommended" in d
