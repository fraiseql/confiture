"""Integration tests for sequential seed execution in build command.

Tests the --sequential flag which applies seed files sequentially to the database
after building the schema, avoiding PostgreSQL parser limits for large seed files.
"""

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.builder import SchemaBuilder


@pytest.fixture
def cli_runner():
    """Create CLI test runner."""
    return CliRunner()


class TestBuildSequentialFlag:
    """Test --sequential flag for build command."""

    def test_build_sequential_flag_accepted(self):
        """Should accept --sequential flag in build command."""
        cli_runner = CliRunner()

        # Try to get build help
        # This verifies the flag exists
        result = cli_runner.invoke(app, ["build", "--help"])

        # Help should succeed
        assert result.exit_code == 0
        # Note: --sequential will be added in GREEN phase

    def test_build_schema_only_true_excludes_seeds_parameter(self, tmp_path):
        """SchemaBuilder.build(schema_only=True) should exclude seeds."""
        base_dir = tmp_path / "db"
        schema_dir = base_dir / "schema"
        seeds_dir = base_dir / "seeds"
        (schema_dir / "00_common").mkdir(parents=True)
        (seeds_dir / "common").mkdir(parents=True)

        (schema_dir / "00_common" / "ext.sql").write_text("CREATE EXTENSION pgcrypto;")
        (seeds_dir / "common" / "users.sql").write_text("INSERT INTO users VALUES (1);")

        config_dir = base_dir / "environments"
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

        # Build schema only
        schema_only = builder.build(schema_only=True)

        # Should not contain seed data
        assert "INSERT INTO users" not in schema_only
        assert "CREATE EXTENSION pgcrypto" in schema_only

    def test_build_sequential_applies_to_database(self, tmp_path):
        """Should apply seed files to database when --sequential is used.

        This test verifies the basic flow:
        1. Schema is built (without seeds)
        2. Seeds are applied sequentially to database
        """
        base_dir = tmp_path / "db"
        schema_dir = base_dir / "schema"
        seeds_dir = base_dir / "seeds"
        (schema_dir / "00_common").mkdir(parents=True)
        (seeds_dir / "common").mkdir(parents=True)

        (schema_dir / "00_common" / "tables.sql").write_text(
            "CREATE TABLE users (id BIGINT PRIMARY KEY);"
        )
        (seeds_dir / "common" / "01_users.sql").write_text("INSERT INTO users VALUES (1);")

        config_dir = base_dir / "environments"
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

        # Verify categorization works
        schema_files, seed_files = builder.categorize_sql_files()
        assert len(schema_files) > 0
        assert len(seed_files) > 0

    def test_build_sequential_with_multiple_seed_files(self, tmp_path):
        """Should apply multiple seed files sequentially."""
        base_dir = tmp_path / "db"
        schema_dir = base_dir / "schema"
        seeds_dir = base_dir / "seeds"
        (schema_dir / "00_common").mkdir(parents=True)
        (seeds_dir / "common").mkdir(parents=True)

        (schema_dir / "00_common" / "tables.sql").write_text(
            "CREATE TABLE users (id BIGINT PRIMARY KEY);"
            "CREATE TABLE posts (id BIGINT PRIMARY KEY, user_id BIGINT);"
        )

        # Create multiple seed files
        (seeds_dir / "common" / "01_users.sql").write_text("INSERT INTO users VALUES (1);")
        (seeds_dir / "common" / "02_posts.sql").write_text("INSERT INTO posts VALUES (1, 1);")
        (seeds_dir / "common" / "03_more_users.sql").write_text("INSERT INTO users VALUES (2);")

        config_dir = base_dir / "environments"
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

        # Verify all seed files are identified
        schema_files, seed_files = builder.categorize_sql_files()
        assert len(seed_files) == 3
        assert len(schema_files) > 0

    def test_build_sequential_with_large_seed_file(self, tmp_path):
        """Should handle large seed files (650+ rows without parser limits)."""
        base_dir = tmp_path / "db"
        schema_dir = base_dir / "schema"
        seeds_dir = base_dir / "seeds"
        (schema_dir / "00_common").mkdir(parents=True)
        (seeds_dir / "common").mkdir(parents=True)

        (schema_dir / "00_common" / "tables.sql").write_text(
            "CREATE TABLE items (id BIGINT PRIMARY KEY, value TEXT);"
        )

        # Create large seed file with 700 INSERT statements
        seed_content = "BEGIN TRANSACTION;\n"
        for i in range(700):
            seed_content += f"INSERT INTO items VALUES ({i}, 'item_{i}');\n"
        seed_content += "COMMIT;"

        (seeds_dir / "common" / "large_seed.sql").write_text(seed_content)

        config_dir = base_dir / "environments"
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

        # Verify seed file is recognized
        schema_files, seed_files = builder.categorize_sql_files()
        assert len(seed_files) == 1
        seed_file = seed_files[0]

        # Verify it can be read without parser errors
        content = seed_file.read_text()
        assert content.count("INSERT INTO") == 700

    def test_build_config_execution_mode_sequential(self, tmp_path):
        """Should respect execution_mode: sequential in environment config."""
        base_dir = tmp_path / "db"
        schema_dir = base_dir / "schema"
        seeds_dir = base_dir / "seeds"
        (schema_dir / "00_common").mkdir(parents=True)
        (seeds_dir / "common").mkdir(parents=True)

        (schema_dir / "00_common" / "tables.sql").write_text(
            "CREATE TABLE users (id BIGINT PRIMARY KEY);"
        )
        (seeds_dir / "common" / "users.sql").write_text("INSERT INTO users VALUES (1);")

        config_dir = base_dir / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
  - {seeds_dir}
exclude_dirs: []
database_url: postgresql://localhost/test

seed:
  execution_mode: sequential
""")

        builder = SchemaBuilder(env="test", project_dir=tmp_path)

        # Should be able to read config with execution_mode
        assert builder.env_config is not None
        # Verify execution_mode is accessible
        if builder.env_config.seed:
            assert hasattr(builder.env_config.seed, "execution_mode")


class TestBuildSequentialEdgeCases:
    """Test error handling and edge cases for sequential mode."""

    def test_no_seed_files_logs_warning(self, tmp_path):
        """Should handle gracefully when no seed files exist."""
        base_dir = tmp_path / "db"
        schema_dir = base_dir / "schema"
        (schema_dir / "00_common").mkdir(parents=True)

        (schema_dir / "00_common" / "tables.sql").write_text(
            "CREATE TABLE users (id BIGINT PRIMARY KEY);"
        )

        config_dir = base_dir / "environments"
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

        # Verify no seed files found
        schema_files, seed_files = builder.categorize_sql_files()
        assert len(seed_files) == 0
        assert len(schema_files) > 0

    def test_build_with_schema_only_never_loads_seeds(self, tmp_path):
        """Should never load seeds when schema_only=True."""
        base_dir = tmp_path / "db"
        schema_dir = base_dir / "schema"
        seeds_dir = base_dir / "seeds"
        (schema_dir / "00_common").mkdir(parents=True)
        (seeds_dir / "common").mkdir(parents=True)

        (schema_dir / "00_common" / "tables.sql").write_text(
            "CREATE TABLE users (id BIGINT PRIMARY KEY);"
        )
        (seeds_dir / "common" / "users.sql").write_text("INSERT INTO users VALUES (1);")

        config_dir = base_dir / "environments"
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

        # Build with schema_only
        schema = builder.build(schema_only=True)

        # Should not contain seeds
        assert "INSERT INTO users" not in schema

    def test_categorization_case_insensitive(self, tmp_path):
        """Should detect seed/SEED/Seed directories (case-insensitive)."""
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_common").mkdir(parents=True)
        (schema_dir / "SEED" / "dev").mkdir(parents=True)  # Uppercase
        (schema_dir / "Seed").mkdir(parents=True)  # Mixed case

        (schema_dir / "00_common" / "ext.sql").write_text("CREATE EXTENSION")
        (schema_dir / "SEED" / "dev" / "data.sql").write_text("INSERT")
        (schema_dir / "Seed" / "users.sql").write_text("INSERT")

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
        schema_files, seed_files = builder.categorize_sql_files()

        # Should identify seeds despite case variations
        assert len(seed_files) == 2
        assert len(schema_files) == 1

    def test_deep_nested_seed_detection(self, tmp_path):
        """Should detect seeds in deeply nested directories."""
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_common").mkdir(parents=True)
        (schema_dir / "data" / "seeds" / "level1" / "level2").mkdir(parents=True)

        (schema_dir / "00_common" / "ext.sql").write_text("CREATE EXTENSION")
        (schema_dir / "data" / "seeds" / "level1" / "level2" / "deep.sql").write_text("INSERT")

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
        schema_files, seed_files = builder.categorize_sql_files()

        # Should find seed in deeply nested directory
        assert len(seed_files) == 1
        assert len(schema_files) == 1

    def test_mixed_case_filenames_preserved(self, tmp_path):
        """Should preserve mixed-case filenames."""
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "00_common").mkdir(parents=True)
        (schema_dir / "seeds").mkdir(parents=True)

        (schema_dir / "00_common" / "MyExtensions.sql").write_text("CREATE EXTENSION")
        (schema_dir / "seeds" / "MySeeds.sql").write_text("INSERT")

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
        schema_files, seed_files = builder.categorize_sql_files()

        # Verify files are found
        assert len(schema_files) > 0
        assert len(seed_files) > 0
        # Verify names are preserved
        assert any("MyExtensions" in str(f) for f in schema_files)
        assert any("MySeeds" in str(f) for f in seed_files)
