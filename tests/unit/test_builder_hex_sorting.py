"""Tests for hexadecimal file sorting feature.

This module tests the SchemaBuilder's ability to sort SQL files using hexadecimal
prefixes (e.g., 0x01_, 0x0A_, 0x14_) for better schema organization and deterministic
ordering that works across different locales and file systems.

The hex sorting feature allows files to be ordered numerically by their hex prefix
rather than alphabetically, enabling more intuitive organization like:
- 0x01_extensions.sql (1)
- 0x0A_tables.sql (10)
- 0x14_views.sql (20)
"""

from pathlib import Path

from confiture.core.builder import SchemaBuilder


def test_hex_file_ordering(tmp_path):
    """Test files with hex prefixes sort correctly."""
    # Create test files
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()

    files = [
        schema_dir / "01F231_late.sql",
        schema_dir / "012311_early.sql",
        schema_dir / "012A31_middle.sql",
    ]

    # Create files with content
    for file in files:
        file.write_text("SELECT 1;")

    # Create config with hex sorting enabled
    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - {schema_dir}
build:
  sort_mode: hex
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    sorted_files = builder.find_sql_files()

    assert sorted_files[0].stem == "012311_early"
    assert sorted_files[1].stem == "012A31_middle"
    assert sorted_files[2].stem == "01F231_late"


def test_mixed_hex_and_alphabetical(tmp_path):
    """Test mixed hex and non-hex files."""
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()

    files = [
        schema_dir / "012A31_hex.sql",
        schema_dir / "abc_alpha.sql",
        schema_dir / "012311_hex2.sql",
    ]

    # Create files with content
    for file in files:
        file.write_text("SELECT 1;")

    # Create config with hex sorting enabled
    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - {schema_dir}
build:
  sort_mode: hex
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    sorted_files = builder.find_sql_files()

    # Hex files first (by hex value), then alphabetical
    assert sorted_files[0].stem == "012311_hex2"
    assert sorted_files[1].stem == "012A31_hex"
    assert sorted_files[2].stem == "abc_alpha"


def test_alphabetical_sorting_default(tmp_path):
    """Test default alphabetical sorting when sort_mode is not hex."""
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()

    files = [
        schema_dir / "z_file.sql",
        schema_dir / "a_file.sql",
        schema_dir / "012311_hex.sql",
    ]

    # Create files with content
    for file in files:
        file.write_text("SELECT 1;")

    # Create config with default sorting
    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - {schema_dir}
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    sorted_files = builder.find_sql_files()

    # Should be alphabetical
    assert sorted_files[0].stem == "012311_hex"
    assert sorted_files[1].stem == "a_file"
    assert sorted_files[2].stem == "z_file"


def test_hex_sort_key_method(tmp_path):
    """Test the _hex_sort_key method directly."""
    # Create test environment
    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("""
database_url: postgresql://localhost/test
include_dirs:
  - /tmp
build:
  sort_mode: hex
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)

    # Test hex prefixed files
    path1 = Path("schema/012311_early.sql")
    path2 = Path("schema/012A31_middle.sql")
    path3 = Path("schema/01F231_late.sql")
    path4 = Path("schema/abc_alpha.sql")

    key1 = builder._hex_sort_key(path1)
    key2 = builder._hex_sort_key(path2)
    key3 = builder._hex_sort_key(path3)
    key4 = builder._hex_sort_key(path4)

    # Hex files should have finite keys
    assert key1[0] == 74513  # 0x012311
    assert key2[0] == 76337  # 0x012A31
    assert key3[0] == 127537  # 0x01F231

    # Non-hex file should have inf key
    assert key4[0] == float("inf")
    assert key4[1] == "abc_alpha"


def test_is_hex_prefix_method(tmp_path):
    """Test the _is_hex_prefix method directly."""
    # Create test environment
    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("""
database_url: postgresql://localhost/test
include_dirs:
  - /tmp
build:
  sort_mode: hex
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)

    # Valid hex prefixes (uppercase)
    assert builder._is_hex_prefix("012311_file")
    assert builder._is_hex_prefix("01F231_file")
    assert builder._is_hex_prefix("ABC123_file")
    assert builder._is_hex_prefix("123_file")

    # Invalid prefixes
    assert not builder._is_hex_prefix("abc_file")  # lowercase
    assert not builder._is_hex_prefix("GHI_file")  # invalid hex chars
    assert not builder._is_hex_prefix("file")  # no prefix
    assert not builder._is_hex_prefix("")  # empty
    assert not builder._is_hex_prefix("123")  # no underscore


def test_hex_sorting_only_when_hex_files_present(tmp_path):
    """Test that hex sorting is only used when hex files are present."""
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()

    # Only non-hex files
    files = [
        schema_dir / "z_file.sql",
        schema_dir / "a_file.sql",
    ]

    # Create files with content
    for file in files:
        file.write_text("SELECT 1;")

    # Create config with hex sorting enabled
    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - {schema_dir}
build:
  sort_mode: hex
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    sorted_files = builder.find_sql_files()

    # Should still be alphabetical since no hex files
    assert sorted_files[0].stem == "a_file"
    assert sorted_files[1].stem == "z_file"
