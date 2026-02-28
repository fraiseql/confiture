"""Tests for StatusResult and MigrationInfo result models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from confiture.models.results import MigrationInfo, StatusResult


class TestMigrationInfo:
    def test_basic_construction(self):
        info = MigrationInfo(version="001", name="add_users", status="applied")
        assert info.version == "001"
        assert info.name == "add_users"
        assert info.status == "applied"
        assert info.applied_at is None

    def test_with_applied_at(self):
        ts = datetime(2026, 2, 28, 12, 0, 0, tzinfo=UTC)
        info = MigrationInfo(version="001", name="add_users", status="applied", applied_at=ts)
        assert info.applied_at == ts

    def test_to_dict_pending(self):
        info = MigrationInfo(version="002", name="add_roles", status="pending")
        d = info.to_dict()
        assert d["version"] == "002"
        assert d["name"] == "add_roles"
        assert d["status"] == "pending"
        assert d["applied_at"] is None

    def test_to_dict_applied_with_timestamp(self):
        ts = datetime(2026, 2, 28, 12, 0, 0, tzinfo=UTC)
        info = MigrationInfo(version="001", name="add_users", status="applied", applied_at=ts)
        d = info.to_dict()
        assert d["applied_at"] == ts.isoformat()


class TestStatusResult:
    def _make_result(
        self,
        *,
        applied: int = 2,
        pending: int = 1,
        tracking_table_exists: bool = True,
    ) -> StatusResult:
        migrations = []
        for i in range(1, applied + 1):
            ts = datetime(2026, 2, i, 10, 0, 0, tzinfo=UTC)
            migrations.append(
                MigrationInfo(
                    version=f"{i:03d}",
                    name=f"migration_{i}",
                    status="applied",
                    applied_at=ts,
                )
            )
        for i in range(applied + 1, applied + pending + 1):
            migrations.append(
                MigrationInfo(version=f"{i:03d}", name=f"migration_{i}", status="pending")
            )
        return StatusResult(
            migrations=migrations,
            tracking_table_exists=tracking_table_exists,
            tracking_table="tb_confiture",
            summary={
                "applied": applied,
                "pending": pending,
                "total": applied + pending,
            },
        )

    def test_has_pending_true(self):
        r = self._make_result(applied=2, pending=1)
        assert r.has_pending is True

    def test_has_pending_false(self):
        r = self._make_result(applied=3, pending=0)
        assert r.has_pending is False

    def test_pending_property_returns_versions(self):
        r = self._make_result(applied=2, pending=2)
        assert r.pending == ["003", "004"]

    def test_applied_property_returns_versions(self):
        r = self._make_result(applied=2, pending=1)
        assert r.applied == ["001", "002"]

    def test_to_dict_structure(self):
        r = self._make_result(applied=1, pending=1)
        d = r.to_dict()
        assert d["tracking_table"] == "tb_confiture"
        assert d["tracking_table_exists"] is True
        assert len(d["migrations"]) == 2
        assert d["summary"]["applied"] == 1
        assert d["summary"]["pending"] == 1
        assert d["summary"]["total"] == 2

    def test_to_dict_migrations_are_dicts(self):
        r = self._make_result(applied=1, pending=0)
        d = r.to_dict()
        assert isinstance(d["migrations"][0], dict)
        assert "version" in d["migrations"][0]

    def test_empty_result(self):
        r = StatusResult(
            migrations=[],
            tracking_table_exists=False,
            tracking_table="tb_confiture",
            summary={"applied": 0, "pending": 0, "total": 0},
        )
        assert r.has_pending is False
        assert r.pending == []
        assert r.applied == []

    def test_tracking_table_absent(self):
        r = self._make_result(applied=0, pending=3, tracking_table_exists=False)
        assert r.tracking_table_exists is False
        assert r.has_pending is True

    def test_unknown_status_not_in_pending_or_applied(self):
        migrations = [
            MigrationInfo(version="001", name="m1", status="unknown"),
            MigrationInfo(version="002", name="m2", status="unknown"),
        ]
        r = StatusResult(
            migrations=migrations,
            tracking_table_exists=False,
            tracking_table="tb_confiture",
            summary={"applied": 0, "pending": 0, "total": 2},
        )
        assert r.pending == []
        assert r.applied == []
        assert r.has_pending is False

    @pytest.mark.parametrize("status", ["applied", "pending", "unknown"])
    def test_migration_info_accepts_all_status_values(self, status):
        info = MigrationInfo(version="001", name="m", status=status)
        assert info.status == status
