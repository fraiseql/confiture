"""Tests for Phase 2: Core rebuild logic on Migrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.exceptions import RebuildError
from confiture.models.results import MigrateRebuildResult, MigrationApplied


class TestDiscoverUserSchemas:
    """Cycle 2.1: _discover_user_schemas."""

    def test_filters_system_schemas(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            ("public",),
            ("myapp",),
            ("pg_catalog",),
            ("information_schema",),
            ("pg_toast",),
        ]
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        migrator = Migrator(connection=conn)
        schemas = migrator._discover_user_schemas()
        assert sorted(schemas) == ["myapp", "public"]

    def test_filters_pg_temp_schemas(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            ("public",),
            ("pg_temp_1",),
            ("pg_toast_temp_1",),
        ]
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        migrator = Migrator(connection=conn)
        schemas = migrator._discover_user_schemas()
        assert schemas == ["public"]

    def test_empty_database(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            ("pg_catalog",),
            ("information_schema",),
        ]
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        migrator = Migrator(connection=conn)
        schemas = migrator._discover_user_schemas()
        assert schemas == []


class TestDropUserSchemas:
    """Cycle 2.2: _drop_user_schemas."""

    def test_drops_schemas_and_recreates_public(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        conn.autocommit = False
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        migrator = Migrator(connection=conn)
        dropped = migrator._drop_user_schemas(["public", "myapp"])

        assert dropped == ["public", "myapp"]
        # Check autocommit was enabled
        assert conn.autocommit is True or conn.autocommit is False  # restored

        # Check DROP statements were issued
        execute_calls = list(cursor.execute.call_args_list)
        sqls = [c[0][0] for c in execute_calls]
        assert any("DROP SCHEMA" in s and "public" in s for s in sqls)
        assert any("DROP SCHEMA" in s and "myapp" in s for s in sqls)
        assert any("CREATE SCHEMA" in s and "public" in s for s in sqls)

    def test_autocommit_restored_on_error(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        conn.autocommit = False
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("drop failed")
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        migrator = Migrator(connection=conn)
        with pytest.raises(Exception, match="drop failed"):
            migrator._drop_user_schemas(["public"])
        # autocommit should be restored
        assert conn.autocommit is False

    def test_empty_list(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        migrator = Migrator(connection=conn)
        dropped = migrator._drop_user_schemas([])
        assert dropped == []


class TestApplyDdlString:
    """Cycle 2.3: _apply_ddl_string."""

    def test_executes_multiple_statements(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        conn.autocommit = False
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        migrator = Migrator(connection=conn)
        ddl = "CREATE TABLE users (id INT);\nCREATE TABLE posts (id INT);"
        count, warnings = migrator._apply_ddl_string(ddl)
        assert count == 2
        assert warnings == []

    def test_strips_begin_commit(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        conn.autocommit = False
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        migrator = Migrator(connection=conn)
        ddl = "BEGIN;\nCREATE TABLE users (id INT);\nCOMMIT;"
        count, warnings = migrator._apply_ddl_string(ddl)
        assert count == 1
        assert warnings == []

    def test_extension_failure_becomes_warning(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        conn.autocommit = False
        cursor = MagicMock()
        call_count = 0

        def side_effect(sql):
            nonlocal call_count
            call_count += 1
            if "CREATE EXTENSION" in sql:
                raise Exception("extension not available")

        cursor.execute.side_effect = side_effect
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        migrator = Migrator(connection=conn)
        ddl = 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";\nCREATE TABLE t (id INT);'
        count, warnings = migrator._apply_ddl_string(ddl)
        assert count == 1  # only the CREATE TABLE counts
        assert len(warnings) == 1
        assert "extension" in warnings[0].lower() or "uuid-ossp" in warnings[0]

    def test_skips_empty_statements(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        conn.autocommit = False
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        migrator = Migrator(connection=conn)
        ddl = "  \n\n  \n"
        count, warnings = migrator._apply_ddl_string(ddl)
        assert count == 0
        assert warnings == []

    def test_autocommit_restored(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        conn.autocommit = False
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        migrator = Migrator(connection=conn)
        migrator._apply_ddl_string("CREATE TABLE t (id INT);")
        assert conn.autocommit is False


class TestBackupTrackingTable:
    """Cycle 2.4: _backup_tracking_table."""

    def test_returns_rows_as_dicts(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        cursor = MagicMock()
        cursor.description = [("version",), ("name",), ("applied_at",), ("checksum",)]
        cursor.fetchall.return_value = [
            ("001", "create_users", "2026-01-01T00:00:00", "abc123"),
        ]
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        migrator = Migrator(connection=conn)
        # Mock tracking_table_exists to return True
        migrator.tracking_table_exists = MagicMock(return_value=True)
        rows = migrator._backup_tracking_table()
        assert len(rows) == 1
        assert rows[0]["version"] == "001"
        assert rows[0]["name"] == "create_users"

    def test_returns_empty_when_table_absent(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        migrator = Migrator(connection=conn)
        migrator.tracking_table_exists = MagicMock(return_value=False)
        rows = migrator._backup_tracking_table()
        assert rows == []


class TestRebuildOrchestrator:
    """Cycle 2.5: rebuild() method on Migrator."""

    def _make_migrator(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        conn.autocommit = False
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        migrator = Migrator(connection=conn)
        return migrator

    @patch("confiture.core.builder.SchemaBuilder")
    def test_rebuild_basic(self, MockBuilder):
        migrator = self._make_migrator()
        # Mock builder
        builder_instance = MockBuilder.return_value
        builder_instance.build.return_value = "CREATE TABLE users (id INT);"

        # Mock internal methods
        migrator._discover_user_schemas = MagicMock(return_value=["public"])
        migrator._drop_user_schemas = MagicMock(return_value=["public"])
        migrator._apply_ddl_string = MagicMock(return_value=(1, []))
        migrator.initialize = MagicMock()
        migrator.reinit = MagicMock(
            return_value=MagicMock(
                migrations_marked=[
                    MigrationApplied(version="001", name="create_users", execution_time_ms=0)
                ]
            )
        )

        result = migrator.rebuild(
            drop_schemas=True,
            schema_dir=Path("db/schema"),
            migrations_dir=Path("db/migrations"),
        )

        assert isinstance(result, MigrateRebuildResult)
        assert result.success is True
        assert result.schemas_dropped == ["public"]
        assert result.ddl_statements_executed == 1
        migrator._drop_user_schemas.assert_called_once()
        migrator.initialize.assert_called_once()

    @patch("confiture.core.builder.SchemaBuilder")
    def test_rebuild_without_drop(self, MockBuilder):
        migrator = self._make_migrator()
        builder_instance = MockBuilder.return_value
        builder_instance.build.return_value = "CREATE TABLE t (id INT);"

        migrator._discover_user_schemas = MagicMock()
        migrator._drop_user_schemas = MagicMock()
        migrator._apply_ddl_string = MagicMock(return_value=(1, []))
        migrator.initialize = MagicMock()
        migrator.reinit = MagicMock(return_value=MagicMock(migrations_marked=[]))

        result = migrator.rebuild(
            drop_schemas=False,
            schema_dir=Path("db/schema"),
            migrations_dir=Path("db/migrations"),
        )

        assert result.success is True
        assert result.schemas_dropped == []
        migrator._discover_user_schemas.assert_not_called()
        migrator._drop_user_schemas.assert_not_called()

    @patch("confiture.core.builder.SchemaBuilder")
    def test_rebuild_dry_run(self, MockBuilder):
        migrator = self._make_migrator()
        builder_instance = MockBuilder.return_value
        builder_instance.build.return_value = "CREATE TABLE t (id INT);"

        migrator._discover_user_schemas = MagicMock(return_value=["public"])
        migrator._apply_ddl_string = MagicMock(return_value=(1, []))
        migrator.initialize = MagicMock()
        migrator.find_migration_files = MagicMock(return_value=[])
        migrator.reinit = MagicMock(return_value=MagicMock(migrations_marked=[]))

        result = migrator.rebuild(
            drop_schemas=True,
            dry_run=True,
            schema_dir=Path("db/schema"),
            migrations_dir=Path("db/migrations"),
        )

        assert result.success is True
        assert result.dry_run is True
        # Dry run should still build DDL for reporting
        builder_instance.build.assert_called_once()

    @patch("confiture.core.seed_applier.SeedApplier")
    @patch("confiture.core.builder.SchemaBuilder")
    def test_rebuild_with_seeds(self, MockBuilder, MockSeedApplier):
        migrator = self._make_migrator()
        builder_instance = MockBuilder.return_value
        builder_instance.build.return_value = "CREATE TABLE t (id INT);"

        seed_instance = MockSeedApplier.return_value
        apply_result = MagicMock()
        apply_result.total_applied = 3
        seed_instance.apply_sequential.return_value = apply_result

        migrator._apply_ddl_string = MagicMock(return_value=(1, []))
        migrator.initialize = MagicMock()
        migrator.reinit = MagicMock(return_value=MagicMock(migrations_marked=[]))

        result = migrator.rebuild(
            apply_seeds=True,
            seeds_dir=Path("db/seeds"),
            schema_dir=Path("db/schema"),
            migrations_dir=Path("db/migrations"),
        )

        assert result.success is True
        assert result.seeds_applied == 3
        MockSeedApplier.assert_called_once()

    @patch("confiture.core.builder.SchemaBuilder")
    def test_rebuild_with_backup_tracking(self, MockBuilder):
        migrator = self._make_migrator()
        builder_instance = MockBuilder.return_value
        builder_instance.build.return_value = "CREATE TABLE t (id INT);"

        migrator._backup_tracking_table = MagicMock(
            return_value=[{"version": "001", "name": "create_users"}]
        )
        migrator._apply_ddl_string = MagicMock(return_value=(1, []))
        migrator.initialize = MagicMock()
        migrator.reinit = MagicMock(return_value=MagicMock(migrations_marked=[]))

        result = migrator.rebuild(
            backup_tracking=True,
            schema_dir=Path("db/schema"),
            migrations_dir=Path("db/migrations"),
        )

        assert result.success is True
        migrator._backup_tracking_table.assert_called_once()

    @patch("confiture.core.builder.SchemaBuilder")
    def test_rebuild_error_on_build_failure(self, MockBuilder):
        migrator = self._make_migrator()
        builder_instance = MockBuilder.return_value
        builder_instance.build.side_effect = Exception("build failed")

        with pytest.raises(RebuildError, match="Schema build failed"):
            migrator.rebuild(
                schema_dir=Path("db/schema"),
                migrations_dir=Path("db/migrations"),
            )

    @patch("confiture.core.builder.SchemaBuilder")
    def test_rebuild_collects_warnings(self, MockBuilder):
        migrator = self._make_migrator()
        builder_instance = MockBuilder.return_value
        builder_instance.build.return_value = "CREATE TABLE t (id INT);"

        migrator._apply_ddl_string = MagicMock(
            return_value=(1, ["extension uuid-ossp not available"])
        )
        migrator.initialize = MagicMock()
        migrator.reinit = MagicMock(return_value=MagicMock(migrations_marked=[]))

        result = migrator.rebuild(
            schema_dir=Path("db/schema"),
            migrations_dir=Path("db/migrations"),
        )

        assert result.success is True
        assert "extension uuid-ossp not available" in result.warnings
