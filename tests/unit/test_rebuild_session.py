"""Tests for the MigratorSession.rebuild() API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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
            migrations_marked=[MigrationApplied(version="001", name="init", duration_ms=0)],
            total_duration_ms=100,
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
            seeds_dir=None,
            env_config=session._config,
        )

    def test_forwards_all_params(self):
        session = self._make_session()
        mock_migrator = MagicMock()
        mock_migrator.rebuild.return_value = MigrateRebuildResult(
            success=True,
            schemas_dropped=[],
            ddl_statements_executed=0,
            migrations_marked=[],
            total_duration_ms=0,
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
            seeds_dir=None,
            env_config=session._config,
        )

    def test_error_outside_context_manager(self):
        from confiture.exceptions import ConfigurationError

        session = self._make_session()
        # _migrator is None by default (before __enter__)
        session._migrator = None

        with pytest.raises(ConfigurationError, match="context manager"):
            session.rebuild()


class TestSessionSeedsDir:
    """A library caller can rebuild with seeds from a directory of their choosing.

    ``baseline.rebuild`` has always read ``seeds_dir`` — it is what the
    ``SeedApplier`` is built from — but the session never passed it, so through
    ``Migrator.from_config`` the directory was fixed at ``db/seeds``.
    """

    def _make_session(self):
        from confiture.core.migrator import MigratorSession

        env = MagicMock()
        env.database_url = "postgresql://localhost/test"
        env.migration = MagicMock()
        env.migration.tracking_table = "tb_confiture"
        return MigratorSession(env, Path("db/migrations"))

    def test_forwards_seeds_dir(self):
        session = self._make_session()
        session._migrator = MagicMock()

        session.rebuild(apply_seeds=True, seeds_dir=Path("db/fixtures"))

        assert session._migrator.rebuild.call_args.kwargs["seeds_dir"] == Path("db/fixtures")

    @patch("confiture.core.seed.applier.SeedApplier")
    @patch("confiture.core.builder.SchemaBuilder", autospec=True)
    def test_seeds_dir_reaches_the_seed_applier(self, MockBuilder, MockSeedApplier, tmp_path):
        """End to end through the facade: forwarding it is not the point, applying
        the seeds it names is."""
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        conn.autocommit = False
        conn.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock())
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        migrator = Migrator(connection=conn)
        migrator._apply_ddl_string = MagicMock(return_value=(1, []))
        migrator.initialize = MagicMock()
        migrator.reinit = MagicMock(return_value=MagicMock(migrations_marked=[]))

        MockBuilder.return_value.build.return_value = "CREATE TABLE t (id INT);"
        MockSeedApplier.return_value.apply_sequential.return_value = MagicMock(succeeded=2)

        session = self._make_session()
        session._migrator = migrator
        seeds = tmp_path / "fixtures"

        result = session.rebuild(apply_seeds=True, seeds_dir=seeds)

        assert MockSeedApplier.call_args.kwargs["seeds_dir"] == seeds
        assert result.seeds_applied == 2

    def test_defaults_to_db_seeds(self):
        """Surfacing the knob does not move anyone's seeds."""
        session = self._make_session()
        session._migrator = MagicMock()

        session.rebuild(apply_seeds=True)

        assert session._migrator.rebuild.call_args.kwargs["seeds_dir"] is None
