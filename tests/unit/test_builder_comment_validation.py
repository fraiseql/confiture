"""Tests for builder integration with comment validation

Tests that SchemaBuilder properly validates comments during build process.
"""

import pytest

from confiture.core.builder import SchemaBuilder
from confiture.exceptions import SchemaError


class TestBuilderCommentValidation:
    """Test SchemaBuilder integration with comment validator"""

    def test_builder_validates_comments_by_default(self, tmp_path):
        """Test that builder validates comments during build"""
        # Create schema directory with files
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # Valid file
        (schema_dir / "01_tables.sql").write_text("CREATE TABLE x (id INT); /* valid */")

        # File with unclosed comment
        (schema_dir / "02_bad.sql").write_text("/* unclosed comment")

        # Setup environment config
        env_config_dir = tmp_path / "db" / "environments"
        env_config_dir.mkdir(parents=True)
        (env_config_dir / "local.yaml").write_text(
            f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []

build:
  sort_mode: alphabetical
  validate_comments:
    enabled: true
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        # Should raise SchemaError due to unclosed comment
        with pytest.raises(SchemaError) as exc_info:
            builder.build()

        assert "unclosed" in str(exc_info.value).lower() or "comment" in str(exc_info.value).lower()

    def test_builder_comment_validation_can_be_disabled(self, tmp_path):
        """Test that comment validation can be disabled"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # File with unclosed comment
        (schema_dir / "01_bad.sql").write_text("/* unclosed comment")

        env_config_dir = tmp_path / "db" / "environments"
        env_config_dir.mkdir(parents=True)
        (env_config_dir / "local.yaml").write_text(
            f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []

build:
  sort_mode: alphabetical
  validate_comments:
    enabled: false
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        # Should NOT raise error since validation is disabled
        schema = builder.build()
        assert schema is not None
        assert len(schema) > 0

    def test_builder_passes_with_valid_comments(self, tmp_path):
        """Test builder succeeds with all valid comments"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        (schema_dir / "01_tables.sql").write_text(
            """
CREATE TABLE users (
    id INT PRIMARY KEY,
    /* This is a valid comment */
    name VARCHAR(255)
);
"""
        )

        (schema_dir / "02_indexes.sql").write_text(
            """
/* Create an index */
CREATE INDEX idx_users_name ON users(name);
"""
        )

        env_config_dir = tmp_path / "db" / "environments"
        env_config_dir.mkdir(parents=True)
        (env_config_dir / "local.yaml").write_text(
            f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []

build:
  sort_mode: alphabetical
  validate_comments:
    enabled: true
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        schema = builder.build()

        # Should succeed and include both files
        assert "users" in schema
        assert "indexes" in schema.lower()

    def test_error_message_includes_file_path(self, tmp_path):
        """Test error message includes problematic file path"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        (schema_dir / "10_tables").mkdir(parents=True)
        (schema_dir / "10_tables" / "users.sql").write_text("/* unclosed")

        env_config_dir = tmp_path / "db" / "environments"
        env_config_dir.mkdir(parents=True)
        (env_config_dir / "local.yaml").write_text(
            f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []

build:
  sort_mode: alphabetical
  validate_comments:
    enabled: true
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        with pytest.raises(SchemaError) as exc_info:
            builder.build()

        error_msg = str(exc_info.value)
        # Error should mention the file
        assert "users.sql" in error_msg or "unclosed" in error_msg.lower()

    def test_builder_includes_validation_in_build_output(self, tmp_path):
        """Test that validation doesn't affect successful builds"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        sql_content = """
CREATE TABLE products (
    id INT PRIMARY KEY,
    /* Column: product name */
    name VARCHAR(255) NOT NULL
);
"""
        (schema_dir / "products.sql").write_text(sql_content)

        env_config_dir = tmp_path / "db" / "environments"
        env_config_dir.mkdir(parents=True)
        (env_config_dir / "local.yaml").write_text(
            f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []

build:
  sort_mode: alphabetical
  validate_comments:
    enabled: true
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        schema = builder.build()

        # Output should be complete
        assert "CREATE TABLE products" in schema
        assert "name VARCHAR" in schema


class TestBuilderCommentValidationConfiguration:
    """Test comment validation configuration options"""

    def test_fail_on_unclosed_blocks_option(self, tmp_path):
        """Test fail_on_unclosed_blocks configuration"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        (schema_dir / "01_schema.sql").write_text("/* unclosed")

        env_config_dir = tmp_path / "db" / "environments"
        env_config_dir.mkdir(parents=True)
        (env_config_dir / "local.yaml").write_text(
            f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []

build:
  sort_mode: alphabetical
  validate_comments:
    enabled: true
    fail_on_unclosed_blocks: true
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        with pytest.raises(SchemaError):
            builder.build()

    def test_fail_on_spillover_option(self, tmp_path):
        """Test fail_on_spillover configuration"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # File that ends inside a comment
        (schema_dir / "01_schema.sql").write_text("SELECT 1;\n/* comment starts")

        env_config_dir = tmp_path / "db" / "environments"
        env_config_dir.mkdir(parents=True)
        (env_config_dir / "local.yaml").write_text(
            f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []

build:
  sort_mode: alphabetical
  validate_comments:
    enabled: true
    fail_on_spillover: true
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        with pytest.raises(SchemaError):
            builder.build()
