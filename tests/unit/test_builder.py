"""Unit tests for SchemaBuilder (Milestone 1.3-1.5)."""

import pytest

from confiture.core.builder import SchemaBuilder
from confiture.exceptions import ConfigurationError, SchemaError


class TestSchemaBuilderFileDiscovery:
    """Test SQL file discovery."""

    def test_find_sql_files_returns_sorted_list(self, tmp_path):
        """Should discover and sort SQL files."""
        # Create test schema structure
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_common").mkdir(parents=True)
        (schema_dir / "10_tables").mkdir(parents=True)
        (schema_dir / "20_views").mkdir(parents=True)

        # Create SQL files (out of order)
        (schema_dir / "20_views" / "user_stats.sql").write_text("CREATE VIEW user_stats")
        (schema_dir / "00_common" / "extensions.sql").write_text("CREATE EXTENSION")
        (schema_dir / "10_tables" / "users.sql").write_text("CREATE TABLE users")
        (schema_dir / "10_tables" / "posts.sql").write_text("CREATE TABLE posts")

        # Create config
        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        # Build and test
        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        files = builder.find_sql_files()

        # Should be sorted alphabetically
        assert len(files) == 4
        assert files[0].name == "extensions.sql"
        assert "00_common" in str(files[0])
        assert files[1].name == "posts.sql"
        assert files[2].name == "users.sql"
        assert files[3].name == "user_stats.sql"

    def test_find_sql_files_excludes_directories(self, tmp_path):
        """Should exclude specified directories."""
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_common").mkdir(parents=True)
        (schema_dir / "scratch").mkdir(parents=True)

        (schema_dir / "00_common" / "extensions.sql").write_text("CREATE EXTENSION")
        (schema_dir / "scratch" / "test.sql").write_text("-- scratch file")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs:
  - {schema_dir / "scratch"}
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        files = builder.find_sql_files()

        # Should only find non-excluded files
        assert len(files) == 1
        assert files[0].name == "extensions.sql"

    def test_find_sql_files_fails_if_directory_missing(self, tmp_path):
        """Should raise error if schema directory doesn't exist."""
        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {tmp_path / "nonexistent"}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        # Error is caught during Environment.load()
        with pytest.raises((SchemaError, ConfigurationError), match="does not exist"):
            SchemaBuilder(env="test", project_dir=tmp_path)

    def test_find_sql_files_fails_if_empty(self, tmp_path):
        """Should raise error if no SQL files found."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)

        with pytest.raises(SchemaError, match="No SQL files found"):
            builder.find_sql_files()


class TestSchemaBuilderBuild:
    """Test schema building."""

    def test_build_concatenates_files_in_order(self, tmp_path):
        """Should concatenate files with headers."""
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_common").mkdir(parents=True)
        (schema_dir / "10_tables").mkdir(parents=True)

        (schema_dir / "00_common" / "ext.sql").write_text(
            "-- extensions\nCREATE EXTENSION pgcrypto;"
        )
        (schema_dir / "10_tables" / "users.sql").write_text(
            "-- users\nCREATE TABLE users (id BIGINT);"
        )

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        schema = builder.build()

        # Should contain header
        assert "PostgreSQL Schema for Confiture" in schema
        assert "Environment: test" in schema

        # Should contain content in order
        assert schema.index("pgcrypto") < schema.index("CREATE TABLE users")

        # Should include file separators
        assert "File: 00_common/ext.sql" in schema
        assert "File: 10_tables/users.sql" in schema

    def test_build_writes_to_file(self, tmp_path):
        """Should write schema to output file."""
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_common").mkdir(parents=True)
        (schema_dir / "00_common" / "test.sql").write_text("CREATE EXTENSION test;")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        output_file = tmp_path / "output" / "schema.sql"

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        schema = builder.build(output_path=output_file)

        # Should write file
        assert output_file.exists()
        assert output_file.read_text() == schema

    def test_build_includes_file_count(self, tmp_path):
        """Should include file count in header."""
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_common").mkdir(parents=True)

        for i in range(5):
            (schema_dir / "00_common" / f"file{i}.sql").write_text(f"-- file {i}")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        schema = builder.build()

        assert "Files Included: 5" in schema


class TestSchemaBuilderHash:
    """Test schema hash computation."""

    def test_compute_hash_is_deterministic(self, tmp_path):
        """Should produce same hash for same content."""
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_common").mkdir(parents=True)
        (schema_dir / "00_common" / "test.sql").write_text("CREATE EXTENSION test;")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)

        hash1 = builder.compute_hash()
        hash2 = builder.compute_hash()

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

    def test_compute_hash_changes_on_content_change(self, tmp_path):
        """Should detect content changes."""
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_common").mkdir(parents=True)
        test_file = schema_dir / "00_common" / "test.sql"
        test_file.write_text("CREATE EXTENSION test;")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)

        hash1 = builder.compute_hash()

        # Modify file
        test_file.write_text("CREATE EXTENSION test2;")

        hash2 = builder.compute_hash()

        assert hash1 != hash2

    def test_compute_hash_changes_on_file_rename(self, tmp_path):
        """Should detect file renames."""
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_common").mkdir(parents=True)
        file1 = schema_dir / "00_common" / "test1.sql"
        file1.write_text("CREATE EXTENSION test;")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)

        hash1 = builder.compute_hash()

        # Rename file (same content, different path)
        file2 = schema_dir / "00_common" / "test2.sql"
        file1.rename(file2)

        hash2 = builder.compute_hash()

        assert hash1 != hash2

    def test_compute_hash_changes_on_file_addition(self, tmp_path):
        """Should detect new files."""
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_common").mkdir(parents=True)
        (schema_dir / "00_common" / "test1.sql").write_text("CREATE EXTENSION test;")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)

        hash1 = builder.compute_hash()

        # Add new file
        (schema_dir / "00_common" / "test2.sql").write_text("CREATE EXTENSION test2;")

        hash2 = builder.compute_hash()

        assert hash1 != hash2


class TestSchemaBuilderPerformance:
    """Test schema builder performance characteristics."""

    def test_build_large_schema(self, tmp_path):
        """Should handle large schemas efficiently."""
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_tables").mkdir(parents=True)

        # Create 100 table files
        for i in range(100):
            table_sql = f"""
CREATE TABLE table_{i:03d} (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pk_table_{i:03d} UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_table_{i:03d}_slug ON table_{i:03d}(slug);
"""
            (schema_dir / "00_tables" / f"table_{i:03d}.sql").write_text(table_sql)

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)

        # Build should complete quickly
        import time

        start = time.perf_counter()
        schema = builder.build()
        duration = time.perf_counter() - start

        # Should be fast (Python implementation)
        assert duration < 1.0  # <1 second for 100 tables

        # Verify all tables included
        assert "table_000" in schema
        assert "table_099" in schema
        assert schema.count("CREATE TABLE") == 100

    def test_hash_computation_is_fast(self, tmp_path):
        """Should compute hashes quickly."""
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_tables").mkdir(parents=True)

        # Create 50 files
        for i in range(50):
            (schema_dir / "00_tables" / f"table_{i:03d}.sql").write_text(
                f"CREATE TABLE table_{i:03d} (id BIGINT PRIMARY KEY);" * 10
            )

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)

        import time

        start = time.perf_counter()
        hash_value = builder.compute_hash()
        duration = time.perf_counter() - start

        assert duration < 0.5  # <500ms for 50 files
        assert len(hash_value) == 64


class TestSchemaBuilderEdgeCases:
    """Test edge cases and error handling."""

    def test_find_common_parent_single_dir(self, tmp_path):
        """Test _find_common_parent with single directory."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "test.sql").write_text("CREATE TABLE test (id INT);")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        files = builder.find_sql_files()

        # _find_common_parent is called internally
        assert len(files) == 1

    def test_build_with_empty_files(self, tmp_path):
        """Test building with empty SQL files."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "empty.sql").write_text("")  # Empty file

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        schema = builder.build()

        # Should handle empty files gracefully
        assert "PostgreSQL Schema" in schema
        # Should include file separators even for empty files
        assert "File: empty.sql" in schema

    def test_build_with_unicode_content(self, tmp_path):
        """Test building with unicode characters."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "unicode.sql").write_text("-- French: Café, Japanese: 日本語, Emoji: 🍓")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        schema = builder.build()

        # Should preserve unicode
        assert "Café" in schema
        assert "日本語" in schema
        assert "🍓" in schema

    def test_compute_hash_with_unicode(self, tmp_path):
        """Test hash computation with unicode."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "unicode.sql").write_text("CREATE TABLE café (id INT);")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        hash1 = builder.compute_hash()

        # Modify unicode content
        (schema_dir / "unicode.sql").write_text("CREATE TABLE café2 (id INT);")
        hash2 = builder.compute_hash()

        # Hashes should differ
        assert hash1 != hash2
