"""Comprehensive tests for SchemaBuilder to reach 90%+ coverage."""

import pytest
from pathlib import Path

from confiture.core.builder import SchemaBuilder
from confiture.exceptions import SchemaError


class TestFindCommonParent:
    """Test _find_common_parent method comprehensively."""

    def test_find_common_parent_multiple_paths(self, tmp_path):
        """Test finding common parent with multiple paths."""
        # Create structure
        schema_dir = tmp_path / "db" / "schema"
        seeds_dir = tmp_path / "db" / "seeds"
        schema_dir.mkdir(parents=True)
        seeds_dir.mkdir(parents=True)

        # Create test files
        (schema_dir / "test.sql").write_text("CREATE TABLE test (id INT);")
        (seeds_dir / "seed.sql").write_text("INSERT INTO test VALUES (1);")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
  - {seeds_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)

        # Common parent should be "db"
        assert "db" in str(builder.base_dir)

    def test_find_common_parent_nested_paths(self, tmp_path):
        """Test finding common parent with deeply nested paths."""
        # Create nested structure
        path1 = tmp_path / "project" / "db" / "schema" / "tables"
        path2 = tmp_path / "project" / "db" / "schema" / "views"
        path1.mkdir(parents=True)
        path2.mkdir(parents=True)

        (path1 / "users.sql").write_text("CREATE TABLE users (id INT);")
        (path2 / "user_view.sql").write_text("CREATE VIEW user_view AS SELECT * FROM users;")

        config_dir = tmp_path / "project" / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {path1}
  - {path2}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path / "project")

        # Common parent should be schema
        assert builder.base_dir.name == "schema"

    def test_find_common_parent_no_common_parts(self, tmp_path):
        """Test _find_common_parent when paths have no common prefix."""
        # Test the method directly
        from confiture.core.builder import SchemaBuilder
        from confiture.config.environment import Environment

        # Create structure to get a builder instance
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

        # Test _find_common_parent directly with paths that have no common prefix
        # Use absolute paths with different roots (simulate)
        path1 = Path("/var/data/schema")
        path2 = Path("/opt/schema")

        # When minimal common parts (just root), should return "/" on Unix or similar
        result = builder._find_common_parent([path1, path2])
        assert result.is_absolute()  # Should return root or similar


class TestFindSqlFilesErrorHandling:
    """Test find_sql_files error handling."""

    def test_find_sql_files_exclude_filtering(self, tmp_path):
        """Test that exclude_dirs properly filters files."""
        schema_dir = tmp_path / "db" / "schema"
        excluded_dir = schema_dir / "excluded"
        schema_dir.mkdir(parents=True)
        excluded_dir.mkdir(parents=True)

        (schema_dir / "included.sql").write_text("CREATE TABLE included (id INT);")
        (excluded_dir / "excluded.sql").write_text("CREATE TABLE excluded (id INT);")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs:
  - {excluded_dir}
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        files = builder.find_sql_files()

        # Should only find included.sql
        assert len(files) == 1
        assert "included.sql" in files[0].name


class TestBuildErrorHandling:
    """Test build method error handling."""

    def test_build_with_file_path_handling(self, tmp_path):
        """Test that build handles relative paths correctly."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        sql_file = schema_dir / "test.sql"
        sql_file.write_text("CREATE TABLE test (id INT);")

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

        # Should include file separator with relative path
        assert "File:" in schema
        assert "test.sql" in schema

    def test_build_error_writing_output(self, tmp_path):
        """Test error handling when output write fails."""
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

        # Try to write to a path that will fail (e.g., a directory)
        invalid_output = tmp_path / "existing_dir"
        invalid_output.mkdir()

        with pytest.raises(SchemaError, match="Error writing schema"):
            builder.build(output_path=invalid_output)


class TestComputeHashErrorHandling:
    """Test compute_hash error handling."""

    def test_compute_hash_includes_path_and_content(self, tmp_path):
        """Test that hash includes both path and content."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        sql_file = schema_dir / "test.sql"
        sql_file.write_text("CREATE TABLE test (id INT);")

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

        # Compute hash
        hash1 = builder.compute_hash()
        assert len(hash1) == 64

        # Rename file (path changes, content same)
        new_file = schema_dir / "renamed.sql"
        sql_file.rename(new_file)

        # Reconfigure to use new file
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder2 = SchemaBuilder(env="test", project_dir=tmp_path)
        hash2 = builder2.compute_hash()

        # Hash should be different (path changed)
        assert hash1 != hash2


class TestBuilderInitialization:
    """Test SchemaBuilder initialization edge cases."""

    def test_initialization_no_include_dirs(self, tmp_path):
        """Test error when no include_dirs specified."""
        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text("""
name: test
include_dirs: []
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        with pytest.raises(SchemaError, match="No include_dirs specified"):
            SchemaBuilder(env="test", project_dir=tmp_path)


class TestBuildWithFileVariations:
    """Test build with various file content scenarios."""

    def test_build_file_without_trailing_newline(self, tmp_path):
        """Test build handles files without trailing newline."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # File without trailing newline
        (schema_dir / "no_newline.sql").write_text("CREATE TABLE test (id INT)")

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

        # Should add newline
        assert schema.endswith("\n")

    def test_build_with_multiple_include_dirs(self, tmp_path):
        """Test building with multiple include directories."""
        schema_dir = tmp_path / "db" / "schema"
        seeds_dir = tmp_path / "db" / "seeds"
        schema_dir.mkdir(parents=True)
        seeds_dir.mkdir(parents=True)

        (schema_dir / "tables.sql").write_text("CREATE TABLE users (id INT);")
        (seeds_dir / "data.sql").write_text("INSERT INTO users VALUES (1);")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
  - {seeds_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        schema = builder.build()

        # Should include files from both directories
        assert "CREATE TABLE users" in schema
        assert "INSERT INTO users" in schema

    def test_build_relative_path_calculation(self, tmp_path):
        """Test that relative paths are calculated correctly."""
        schema_dir = tmp_path / "project" / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "test.sql").write_text("CREATE TABLE test (id INT);")

        config_dir = tmp_path / "project" / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path / "project")
        schema = builder.build()

        # Should contain relative path in file header
        assert "File:" in schema
        assert "test.sql" in schema
