"""Tests for Phase 1: rebuild foundation (exceptions, results, config, strategy parser)."""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.exceptions import ConfiturError, RebuildError
from confiture.models.results import MigrateRebuildResult, MigrationApplied


class TestRebuildError:
    """Cycle 1.1: RebuildError exception."""

    def test_importable_from_exceptions(self):
        assert RebuildError is not None

    def test_inherits_confiture_error(self):
        assert issubclass(RebuildError, ConfiturError)

    def test_can_raise_and_catch(self):
        with pytest.raises(RebuildError, match="rebuild failed"):
            raise RebuildError("rebuild failed")

    def test_caught_by_confiture_error(self):
        with pytest.raises(ConfiturError):
            raise RebuildError("rebuild failed")

    def test_supports_error_code(self):
        err = RebuildError("fail", error_code="REBUILD_001")
        assert err.error_code == "REBUILD_001"


class TestMigrateRebuildResult:
    """Cycle 1.2: MigrateRebuildResult dataclass."""

    def test_basic_fields(self):
        result = MigrateRebuildResult(
            success=True,
            schemas_dropped=["public", "myapp"],
            ddl_statements_executed=15,
            migrations_marked=[],
            total_execution_time_ms=500,
            dry_run=False,
        )
        assert result.success is True
        assert result.schemas_dropped == ["public", "myapp"]
        assert result.ddl_statements_executed == 15
        assert result.total_execution_time_ms == 500
        assert result.dry_run is False
        assert result.warnings == []
        assert result.error is None
        assert result.seeds_applied is None
        assert result.verified is None

    def test_to_dict_serialization(self):
        applied = MigrationApplied(version="001", name="create_users", execution_time_ms=0)
        result = MigrateRebuildResult(
            success=True,
            schemas_dropped=["public"],
            ddl_statements_executed=10,
            migrations_marked=[applied],
            total_execution_time_ms=200,
            dry_run=False,
            warnings=["extension warning"],
            seeds_applied=3,
            verified=True,
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["schemas_dropped"] == ["public"]
        assert d["ddl_statements_executed"] == 10
        assert len(d["migrations_marked"]) == 1
        assert d["migrations_marked"][0]["version"] == "001"
        assert d["total_execution_time_ms"] == 200
        assert d["dry_run"] is False
        assert d["warnings"] == ["extension warning"]
        assert d["seeds_applied"] == 3
        assert d["verified"] is True

    def test_to_dict_with_error(self):
        result = MigrateRebuildResult(
            success=False,
            schemas_dropped=[],
            ddl_statements_executed=0,
            migrations_marked=[],
            total_execution_time_ms=50,
            dry_run=False,
            error="Connection refused",
        )
        d = result.to_dict()
        assert d["success"] is False
        assert d["error"] == "Connection refused"

    def test_default_optional_fields(self):
        result = MigrateRebuildResult(
            success=True,
            schemas_dropped=[],
            ddl_statements_executed=0,
            migrations_marked=[],
            total_execution_time_ms=0,
            dry_run=True,
        )
        d = result.to_dict()
        assert d["seeds_applied"] is None
        assert d["verified"] is None
        assert d["error"] is None
        assert d["warnings"] == []


class TestRebuildThresholdConfig:
    """Cycle 1.3: rebuild_threshold on MigrationConfig."""

    def test_default_value(self):
        from confiture.config.environment import MigrationConfig

        config = MigrationConfig()
        assert config.rebuild_threshold == 5

    def test_custom_value(self):
        from confiture.config.environment import MigrationConfig

        config = MigrationConfig(rebuild_threshold=10)
        assert config.rebuild_threshold == 10

    def test_zero_value(self):
        from confiture.config.environment import MigrationConfig

        config = MigrationConfig(rebuild_threshold=0)
        assert config.rebuild_threshold == 0


class TestStrategyParser:
    """Cycle 1.4: Strategy header parser."""

    def test_parse_rebuild_strategy(self):
        from confiture.core.strategy import parse_migration_strategy

        sql = "-- Strategy: rebuild\nCREATE TABLE users (id INT);"
        assert parse_migration_strategy(sql) == "rebuild"

    def test_parse_incremental_strategy(self):
        from confiture.core.strategy import parse_migration_strategy

        sql = "-- Strategy: incremental\nALTER TABLE users ADD COLUMN name TEXT;"
        assert parse_migration_strategy(sql) == "incremental"

    def test_no_strategy_header(self):
        from confiture.core.strategy import parse_migration_strategy

        sql = "CREATE TABLE users (id INT);"
        assert parse_migration_strategy(sql) is None

    def test_case_insensitive(self):
        from confiture.core.strategy import parse_migration_strategy

        sql = "-- STRATEGY: Rebuild\nCREATE TABLE users (id INT);"
        assert parse_migration_strategy(sql) == "rebuild"

    def test_strategy_with_extra_whitespace(self):
        from confiture.core.strategy import parse_migration_strategy

        sql = "--   Strategy:   rebuild  \nCREATE TABLE users (id INT);"
        assert parse_migration_strategy(sql) == "rebuild"

    def test_strategy_in_line_10(self):
        from confiture.core.strategy import parse_migration_strategy

        lines = ["-- comment"] * 9 + ["-- Strategy: rebuild", "CREATE TABLE t (id INT);"]
        sql = "\n".join(lines)
        assert parse_migration_strategy(sql) == "rebuild"

    def test_strategy_in_line_11_not_found(self):
        from confiture.core.strategy import parse_migration_strategy

        lines = ["-- comment"] * 10 + ["-- Strategy: rebuild", "CREATE TABLE t (id INT);"]
        sql = "\n".join(lines)
        assert parse_migration_strategy(sql) is None

    def test_parse_file_strategy(self, tmp_path: Path):
        from confiture.core.strategy import parse_file_strategy

        f = tmp_path / "001_create_users.up.sql"
        f.write_text("-- Strategy: rebuild\nCREATE TABLE users (id INT);")
        assert parse_file_strategy(f) == "rebuild"

    def test_parse_file_strategy_no_header(self, tmp_path: Path):
        from confiture.core.strategy import parse_file_strategy

        f = tmp_path / "001_create_users.up.sql"
        f.write_text("CREATE TABLE users (id INT);")
        assert parse_file_strategy(f) is None

    def test_find_rebuild_strategy_files(self, tmp_path: Path):
        from confiture.core.strategy import find_rebuild_strategy_files

        (tmp_path / "001_create_users.up.sql").write_text(
            "-- Strategy: rebuild\nCREATE TABLE users (id INT);"
        )
        (tmp_path / "002_add_index.up.sql").write_text(
            "-- Strategy: incremental\nCREATE INDEX idx ON users (id);"
        )
        (tmp_path / "003_add_posts.up.sql").write_text("CREATE TABLE posts (id INT);")
        (tmp_path / "004_rebuild_views.up.sql").write_text(
            "-- Strategy: rebuild\nCREATE VIEW v AS SELECT 1;"
        )
        result = find_rebuild_strategy_files(tmp_path)
        names = [p.name for p in result]
        assert "001_create_users.up.sql" in names
        assert "004_rebuild_views.up.sql" in names
        assert len(result) == 2

    def test_find_rebuild_strategy_files_empty_dir(self, tmp_path: Path):
        from confiture.core.strategy import find_rebuild_strategy_files

        result = find_rebuild_strategy_files(tmp_path)
        assert result == []
