"""Test error paths for SchemaBuilder to improve coverage."""


import pytest

from confiture.core.builder import SchemaBuilder
from confiture.exceptions import ConfigurationError


class TestBuilderErrorPaths:
    """Test error handling in SchemaBuilder."""

    def test_builder_initialization_invalid_env(self, tmp_path):
        """Test builder with non-existent environment."""
        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)

        with pytest.raises(ConfigurationError):
            SchemaBuilder(env="nonexistent", project_dir=tmp_path)

    def test_build_creates_output_directory(self, tmp_path):
        """Test that build creates output directory if it doesn't exist."""
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

        # Output directory doesn't exist yet
        output_file = tmp_path / "nonexistent_dir" / "output.sql"

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        builder.build(output_path=output_file)

        # Directory should be created
        assert output_file.parent.exists()
        assert output_file.exists()

    def test_find_sql_files_with_nested_directories(self, tmp_path):
        """Test finding SQL files in deeply nested directories."""
        schema_dir = tmp_path / "db" / "schema"
        nested_dir = schema_dir / "00_common" / "functions" / "user_functions"
        nested_dir.mkdir(parents=True)

        (nested_dir / "func1.sql").write_text("CREATE FUNCTION func1() RETURNS INT;")

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

        assert len(files) == 1
        assert "func1.sql" in files[0].name

    def test_compute_hash_with_large_files(self, tmp_path):
        """Test hash computation with large SQL files."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # Create large file (>1MB)
        large_content = "CREATE TABLE large_table (id INT);\n" * 100000
        (schema_dir / "large.sql").write_text(large_content)

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
        hash_value = builder.compute_hash()

        # Should handle large files
        assert len(hash_value) == 64  # SHA256

    def test_build_with_only_comments(self, tmp_path):
        """Test building schema with files containing only comments."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "comments.sql").write_text(
            """
-- This is just a comment file
-- No actual SQL statements
-- Just documentation
"""
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

        # Should handle comment-only files
        assert "This is just a comment file" in schema
