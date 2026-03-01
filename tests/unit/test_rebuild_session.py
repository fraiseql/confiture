"""Tests for Phase 3: MigratorSession.rebuild() API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from confiture.models.results import MigrateRebuildResult, MigrationApplied


class TestMigratorSessionRebuild:
    """Cycle 3.1: MigratorSession.rebuild()."""

    def _make_session(self):
        from confiture.core.migrator import MigratorSession

        env = MagicMock()
        env.database_url = "postgresql://localhost/test"
        env.migration = MagicMock()
        env.migration.tracking_table = "tb_confiture"
        session = MigratorSession(env, Path("db/migrations"))
        return session

    def test_delegates_to_migrator_rebuild(self):
        session = self._make_session()
        mock_migrator = MagicMock()
        expected_result = MigrateRebuildResult(
            success=True,
            schemas_dropped=["public"],
            ddl_statements_executed=5,
            migrations_marked=[MigrationApplied(version="001", name="init", execution_time_ms=0)],
            total_execution_time_ms=100,
            dry_run=False,
        )
        mock_migrator.rebuild.return_value = expected_result
        session._migrator = mock_migrator

        result = session.rebuild(drop_schemas=True)

        assert result is expected_result
        mock_migrator.rebuild.assert_called_once_with(
            drop_schemas=True,
            dry_run=False,
            apply_seeds=False,
            backup_tracking=False,
            migrations_dir=Path("db/migrations"),
        )

    def test_forwards_all_params(self):
        session = self._make_session()
        mock_migrator = MagicMock()
        mock_migrator.rebuild.return_value = MigrateRebuildResult(
            success=True,
            schemas_dropped=[],
            ddl_statements_executed=0,
            migrations_marked=[],
            total_execution_time_ms=0,
            dry_run=True,
        )
        session._migrator = mock_migrator

        session.rebuild(
            drop_schemas=True,
            dry_run=True,
            apply_seeds=True,
            backup_tracking=True,
        )

        mock_migrator.rebuild.assert_called_once_with(
            drop_schemas=True,
            dry_run=True,
            apply_seeds=True,
            backup_tracking=True,
            migrations_dir=Path("db/migrations"),
        )

    def test_error_outside_context_manager(self):
        session = self._make_session()
        # _migrator is None by default (before __enter__)
        session._migrator = None

        with pytest.raises(AssertionError, match="'with' block"):
            session.rebuild()
