"""Tests for dynamic schema discovery with glob patterns."""

import pytest

from confiture.core.builder import SchemaBuilder
from confiture.exceptions import ConfigurationError

"""Tests for dynamic SQL file discovery feature.

This module tests the SchemaBuilder's enhanced file discovery capabilities,
including pattern-based inclusion/exclusion, recursive directory traversal,
and auto-discovery of schema directories.

Key features tested:
- Include/exclude patterns for selective file discovery
- Recursive vs non-recursive directory scanning
- Auto-discovery mode for flexible project structures
- Multiple include directory configurations
"""


def test_auto_discover_skips_missing_directories(tmp_path):
    """Test auto-discover mode skips non-existent directories."""
    existing_dir = tmp_path / "existing"
    missing_dir = tmp_path / "missing"

    existing_dir.mkdir()
    (existing_dir / "file.sql").write_text("SELECT 1;")

    # Create config with auto_discover enabled
    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - path: {existing_dir}
    auto_discover: true
  - path: {missing_dir}
    auto_discover: true
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    files = builder.find_sql_files()

    assert len(files) == 1  # Only from existing_dir


def test_exclude_patterns(tmp_path):
    """Test exclude patterns filter files correctly."""
    schema_dir = tmp_path / "schema"
    (schema_dir / "temp").mkdir(parents=True)

    keep_file = schema_dir / "keep.sql"
    backup_file = schema_dir / "backup.sql.bak"
    temp_file = schema_dir / "temp" / "temp.sql"

    keep_file.write_text("SELECT 1;")
    backup_file.write_text("SELECT 2;")
    temp_file.write_text("SELECT 3;")

    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - path: {schema_dir}
    exclude:
      - "**/*.bak"
      - "temp/**"
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    files = builder.find_sql_files()

    assert len(files) == 1
    assert "keep.sql" in str(files[0])


def test_include_patterns(tmp_path):
    """Test include patterns match files correctly."""
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()

    sql_file = schema_dir / "table.sql"
    txt_file = schema_dir / "readme.txt"
    backup_file = schema_dir / "table.sql.bak"

    sql_file.write_text("CREATE TABLE test (id INT);")
    txt_file.write_text("This is a readme")
    backup_file.write_text("CREATE TABLE backup (id INT);")

    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - path: {schema_dir}
    include:
      - "**/*.sql"
    exclude:
      - "**/*.bak"
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    files = builder.find_sql_files()

    assert len(files) == 1
    assert "table.sql" in str(files[0])
    assert "readme.txt" not in str(files[0])
    assert "backup" not in str(files[0])


def test_custom_include_patterns(tmp_path):
    """Test custom include patterns work."""
    schema_dir = tmp_path / "schema"
    (schema_dir / "migrations").mkdir(parents=True)

    migration_file = schema_dir / "migrations" / "001_create_users.up.sql"
    seed_file = schema_dir / "seeds" / "users.sql"
    view_file = schema_dir / "views" / "user_view.sql"

    # Create directories
    (schema_dir / "seeds").mkdir()
    (schema_dir / "views").mkdir()

    migration_file.write_text("CREATE TABLE users (id INT);")
    seed_file.write_text("INSERT INTO users VALUES (1);")
    view_file.write_text("CREATE VIEW user_view AS SELECT * FROM users;")

    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - path: {schema_dir}
    include:
      - "**/*.up.sql"
      - "**/seeds/*.sql"
    exclude:
      - "**/views/**"
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    files = builder.find_sql_files()

    assert len(files) == 2
    filenames = [f.name for f in files]
    assert "001_create_users.up.sql" in filenames
    assert "users.sql" in filenames
    assert "user_view.sql" not in filenames


def test_non_recursive_with_patterns(tmp_path):
    """Test non-recursive directory with include patterns."""
    schema_dir = tmp_path / "schema"
    (schema_dir / "subdir").mkdir(parents=True)

    root_file = schema_dir / "root.sql"
    nested_file = schema_dir / "subdir" / "nested.sql"

    root_file.write_text("SELECT 1;")
    nested_file.write_text("SELECT 2;")

    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - path: {schema_dir}
    recursive: false
    include:
      - "*.sql"
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    files = builder.find_sql_files()

    assert len(files) == 1
    assert "root.sql" in str(files[0])


def test_auto_discover_disabled_raises_error(tmp_path):
    """Test that disabled auto_discover raises error for missing directories."""
    missing_dir = tmp_path / "missing"

    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - path: {missing_dir}
    auto_discover: false
""")

    with pytest.raises(ConfigurationError, match="Include directory does not exist"):
        SchemaBuilder(env="test", project_dir=tmp_path)


def test_multiple_include_dirs_with_patterns(tmp_path):
    """Test multiple include directories with different patterns."""
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"

    dir1.mkdir()
    dir2.mkdir()

    (dir1 / "table1.sql").write_text("CREATE TABLE table1 (id INT);")
    (dir1 / "view1.sql").write_text("CREATE VIEW view1 AS SELECT 1;")
    (dir2 / "table2.sql").write_text("CREATE TABLE table2 (id INT);")
    (dir2 / "data.sql").write_text("INSERT INTO table2 VALUES (1);")

    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - path: {dir1}
    include:
      - "**/table*.sql"
    order: 10
  - path: {dir2}
    include:
      - "**/table*.sql"
      - "**/data.sql"
    order: 20
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    files = builder.find_sql_files()

    assert len(files) == 3
    # Should be ordered by directory order first, then alphabetically within each dir
    filenames = [f.name for f in files]
    assert filenames[0] == "table1.sql"  # dir1, order 10
    assert "table2.sql" in filenames
    assert "data.sql" in filenames
