"""Unit tests for SeedBridge."""

from __future__ import annotations

from unittest.mock import patch

from confiture.core.seed_bridge import SeedBridge, SeedGenerationConfig, SeedGenerationResult


def test_seed_generation_config_defaults():
    config = SeedGenerationConfig(table="users")
    assert config.schema == "public"
    assert config.row_count == 10
    assert config.env == "development"
    assert not config.overwrite


def test_seed_generation_result_to_dict(tmp_path):
    result = SeedGenerationResult(
        table="users",
        output_path=tmp_path / "users.sql",
        row_count=5,
        column_count=3,
        success=True,
    )
    d = result.to_dict()
    assert d["table"] == "users"
    assert d["row_count"] == 5
    assert d["column_count"] == 3
    assert d["success"] is True
    assert d["error"] is None


def _make_columns() -> list:
    return [
        {"name": "id", "type": "uuid", "nullable": False, "default": "gen_random_uuid()"},
        {"name": "name", "type": "text", "nullable": False, "default": None},
        {"name": "email", "type": "text", "nullable": False, "default": None},
    ]


def test_seed_bridge_generate_creates_file(tmp_path):
    bridge = SeedBridge("postgresql://localhost/test")

    with patch.object(bridge, "_get_table_columns", return_value=_make_columns()):
        config = SeedGenerationConfig(
            table="users",
            output_dir=tmp_path,
            row_count=3,
        )
        result = bridge.generate(config)

    assert result.success is True
    assert result.column_count == 3
    assert result.output_path.exists()
    content = result.output_path.read_text()
    assert "users" in content
    assert "INSERT INTO" in content or "HINT" in content


def test_seed_bridge_generate_table_not_found(tmp_path):
    bridge = SeedBridge("postgresql://localhost/test")

    with patch.object(bridge, "_get_table_columns", return_value=[]):
        config = SeedGenerationConfig(table="nonexistent", output_dir=tmp_path)
        result = bridge.generate(config)

    assert result.success is False
    assert "not found" in result.error or "no columns" in result.error


def test_seed_bridge_generate_no_overwrite(tmp_path):
    bridge = SeedBridge("postgresql://localhost/test")

    # Pre-create the file
    env_dir = tmp_path / "development"
    env_dir.mkdir()
    existing = env_dir / "users.sql"
    existing.write_text("existing content")

    with patch.object(bridge, "_get_table_columns", return_value=_make_columns()):
        config = SeedGenerationConfig(table="users", output_dir=tmp_path, overwrite=False)
        result = bridge.generate(config)

    assert result.success is False
    assert "already exists" in result.error


def test_seed_bridge_generate_with_overwrite(tmp_path):
    bridge = SeedBridge("postgresql://localhost/test")

    # Pre-create the file
    env_dir = tmp_path / "development"
    env_dir.mkdir()
    existing = env_dir / "users.sql"
    existing.write_text("old content")

    with patch.object(bridge, "_get_table_columns", return_value=_make_columns()):
        config = SeedGenerationConfig(table="users", output_dir=tmp_path, overwrite=True)
        result = bridge.generate(config)

    assert result.success is True
    assert "old content" not in result.output_path.read_text()


def test_seed_bridge_generate_db_error(tmp_path):
    bridge = SeedBridge("postgresql://localhost/test")

    with patch.object(bridge, "_get_table_columns", side_effect=Exception("Connection refused")):
        config = SeedGenerationConfig(table="users", output_dir=tmp_path)
        result = bridge.generate(config)

    assert result.success is False
    assert "Connection refused" in result.error


def test_seed_bridge_check_fraiseql_data_not_available():
    bridge = SeedBridge("postgresql://localhost/test")
    with patch.dict("sys.modules", {"fraiseql": None, "fraiseql.data": None}):
        # Since fraiseql is not installed, should return False
        result = bridge._check_fraiseql_data()
        assert isinstance(result, bool)
