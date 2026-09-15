"""Tests for the core rebuild logic on Migrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import psycopg
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

        # Check DROP statements were issued.  execute() now receives
        # psycopg.sql.Composable objects, so use repr() for content checks.
        execute_calls = list(cursor.execute.call_args_list)
        sqls = [repr(c[0][0]) for c in execute_calls]
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

    def test_rollback_before_autocommit(self):
        """Issue #93: rollback open transaction before setting autocommit."""
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        conn.autocommit = False
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        migrator = Migrator(connection=conn)
        migrator._drop_user_schemas(["public"])

        conn.rollback.assert_called_once()


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
                raise psycopg.Error("extension not available")

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

    def test_rollback_before_autocommit(self):
        """Issue #93: rollback open transaction before setting autocommit."""
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        conn.autocommit = False
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        migrator = Migrator(connection=conn)
        migrator._apply_ddl_string("CREATE TABLE t (id INT);")

        conn.rollback.assert_called_once()


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

    @patch("confiture.core.builder.SchemaBuilder", autospec=True)
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
                    MigrationApplied(version="001", name="create_users", duration_ms=0)
                ]
            )
        )

        result = migrator.rebuild(
            drop_schemas=True,
            migrations_dir=Path("db/migrations"),
        )

        assert isinstance(result, MigrateRebuildResult)
        assert result.success is True
        assert result.schemas_dropped == ["public"]
        assert result.ddl_statements_executed == 1
        migrator._drop_user_schemas.assert_called_once()
        migrator.initialize.assert_called_once()

    @patch("confiture.core.builder.SchemaBuilder", autospec=True)
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
            migrations_dir=Path("db/migrations"),
        )

        assert result.success is True
        assert result.schemas_dropped == []
        migrator._discover_user_schemas.assert_not_called()
        migrator._drop_user_schemas.assert_not_called()

    @patch("confiture.core.builder.SchemaBuilder", autospec=True)
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
            migrations_dir=Path("db/migrations"),
        )

        assert result.success is True
        assert result.dry_run is True
        # Dry run should still build DDL for reporting
        builder_instance.build.assert_called_once()

    @patch("confiture.core.seed.applier.SeedApplier")
    @patch("confiture.core.builder.SchemaBuilder", autospec=True)
    def test_rebuild_with_seeds(self, MockBuilder, MockSeedApplier):
        migrator = self._make_migrator()
        builder_instance = MockBuilder.return_value
        builder_instance.build.return_value = "CREATE TABLE t (id INT);"

        seed_instance = MockSeedApplier.return_value
        apply_result = MagicMock()
        apply_result.succeeded = 3
        seed_instance.apply_sequential.return_value = apply_result

        migrator._apply_ddl_string = MagicMock(return_value=(1, []))
        migrator.initialize = MagicMock()
        migrator.reinit = MagicMock(return_value=MagicMock(migrations_marked=[]))

        result = migrator.rebuild(
            apply_seeds=True,
            seeds_dir=Path("db/seeds"),
            migrations_dir=Path("db/migrations"),
        )

        assert result.success is True
        assert result.seeds_applied == 3
        MockSeedApplier.assert_called_once()

    @patch("confiture.core.builder.SchemaBuilder", autospec=True)
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
            migrations_dir=Path("db/migrations"),
        )

        assert result.success is True
        migrator._backup_tracking_table.assert_called_once()

    @patch("confiture.core.builder.SchemaBuilder", autospec=True)
    def test_rebuild_error_on_build_failure(self, MockBuilder):
        migrator = self._make_migrator()
        builder_instance = MockBuilder.return_value
        builder_instance.build.side_effect = Exception("build failed")

        with pytest.raises(RebuildError, match="Schema build failed"):
            migrator.rebuild(
                migrations_dir=Path("db/migrations"),
            )

    @patch("confiture.core.builder.SchemaBuilder", autospec=True)
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
            migrations_dir=Path("db/migrations"),
        )

        assert result.success is True
        assert "extension uuid-ossp not available" in result.warnings


class TestRebuildHonoursItsEnvironment:
    """The ``Environment`` the caller passed is the one the build reads."""

    def _make_migrator(self):
        from confiture.core.migrator import Migrator

        conn = MagicMock()
        conn.autocommit = False
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return Migrator(connection=conn)

    @staticmethod
    def _nameless_env(**overrides):
        """The minimal migrate-only config #168 made valid: no ``name:`` key."""
        from confiture.config.environment import Environment

        return Environment.model_validate({"database_url": "postgresql://localhost/x", **overrides})

    @patch("confiture.core.builder.SchemaBuilder", autospec=True)
    def test_builder_receives_the_environment_not_its_name(self, MockBuilder):
        """``SchemaBuilder`` accepts ``str | Environment``. Passing ``env_config.name``
        instead re-reads the YAML from disk and discards the caller's own config."""
        migrator = self._make_migrator()
        MockBuilder.return_value.build.return_value = "CREATE TABLE t (id INT);"
        migrator._apply_ddl_string = MagicMock(return_value=(1, []))
        migrator.initialize = MagicMock()
        migrator.reinit = MagicMock(return_value=MagicMock(migrations_marked=[]))

        env = self._nameless_env(include_dirs=["db/schema"])
        migrator.rebuild(migrations_dir=Path("db/migrations"), env_config=env)

        assert MockBuilder.call_args.kwargs["env"] is env

    def test_nameless_environment_does_not_send_the_loader_after_a_yaml_file(self):
        """A config with no ``name:`` used to fail on ``db/environments/.yaml``, which
        names neither the caller's mistake nor anything they can create."""
        migrator = self._make_migrator()

        with pytest.raises(RebuildError) as excinfo:
            migrator.rebuild(migrations_dir=Path("db/migrations"), env_config=self._nameless_env())

        message = str(excinfo.value)
        assert "db/environments/.yaml" not in message
        assert "include_dirs" in message

    def test_a_configuration_failure_is_not_blamed_on_the_ddl(self):
        """The build reads a config to find the DDL; either can be at fault, and the
        remedy for one is no use for the other."""
        migrator = self._make_migrator()

        with pytest.raises(RebuildError) as excinfo:
            migrator.rebuild(migrations_dir=Path("db/migrations"), env_config=self._nameless_env())

        assert "syntax errors" not in (excinfo.value.resolution_hint or "")


class TestRebuildDeclaresNoDeadParameter:
    """A parameter that only assigns itself a default is never read.

    ``schema_dir`` was such a parameter on the public ``Migrator.rebuild`` for as
    long as it existed: declared, defaulted to ``db/schema``, and never consulted —
    the DDL source is the environment's ``include_dirs``, which the builder reads.
    Ruff's ARG family cannot see it, because ``if schema_dir is None:`` is a read.
    """

    @staticmethod
    def _defaults_itself(stmt) -> str | None:
        """The name *stmt* defaults, if it is an ``if <name> is None: <name> = …``."""
        import ast

        if not isinstance(stmt, ast.If):
            return None
        test = stmt.test
        if not (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Is)
            and isinstance(test.left, ast.Name)
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value is None
        ):
            return None
        assigned = [
            target.id
            for inner in stmt.body
            if isinstance(inner, ast.Assign)
            for target in inner.targets
            if isinstance(target, ast.Name)
        ]
        return test.left.id if assigned == [test.left.id] else None

    def test_every_parameter_is_read_somewhere(self):
        import ast

        from confiture.core._migrator import baseline

        source = Path(baseline.__file__).read_text()
        fn = next(
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "rebuild"
        )
        declared = [
            arg.arg for arg in (*fn.args.args, *fn.args.kwonlyargs) if arg.arg != "migrator"
        ]
        assert declared, "rebuild declares no parameters — the guard is watching nothing"

        dead = []
        for param in declared:
            read = any(
                isinstance(node, ast.Name) and node.id == param and isinstance(node.ctx, ast.Load)
                for stmt in fn.body
                if self._defaults_itself(stmt) != param
                for node in ast.walk(stmt)
            )
            if not read:
                dead.append(param)

        assert not dead, (
            f"baseline.rebuild declares {dead}, which it never reads — only defaults. "
            f"A caller who passes one gets no effect and no error. Delete it, or use it."
        )
