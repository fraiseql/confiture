"""Integration tests for schema builder with all validation features

Tests the complete validation pipeline combining:
- Comment validation
- Configurable separators
- Optional SQL linting
"""

import pytest

from confiture.core.builder import SchemaBuilder
from confiture.exceptions import SchemaError


class TestFullValidationPipeline:
    """Test all three validation features working together"""

    def test_all_features_enabled_valid_schema(self, tmp_path):
        """Test valid schema passes all three validations"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # Create well-formed SQL files
        (schema_dir / "01_tables.sql").write_text(
            """
-- Table: users
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    /* Column: user name */
    name VARCHAR(255) NOT NULL
);
"""
        )

        (schema_dir / "02_indexes.sql").write_text(
            """
-- Index: idx_users_name
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
  separators:
    style: block_comment
  lint:
    enabled: false
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        schema = builder.build()

        # Should succeed with all validations passing
        assert schema is not None
        assert "CREATE TABLE users" in schema
        assert "CREATE INDEX idx_users_name" in schema
        # Should have block comment separators
        assert "/*" in schema
        assert "*/" in schema

    def test_comment_validation_fails_before_build(self, tmp_path):
        """Test comment validation fails before separator generation"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # File with unclosed comment
        (schema_dir / "01_schema.sql").write_text("/* Unclosed comment")
        (schema_dir / "02_schema.sql").write_text("CREATE TABLE t (id INT);")

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
  validate_comments:
    enabled: true
  separators:
    style: block_comment
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        # Should raise error during validation (before build)
        with pytest.raises(SchemaError) as exc_info:
            builder.build()

        assert "unclosed" in str(exc_info.value).lower() or "comment" in str(exc_info.value).lower()

    def test_disabled_validation_allows_bad_comments(self, tmp_path):
        """Test disabling comment validation allows spillover"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # File ending with unclosed comment
        (schema_dir / "01_schema.sql").write_text("/* This comment")
        (schema_dir / "02_schema.sql").write_text("CREATE TABLE t (id INT);")

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
  validate_comments:
    enabled: false
  separators:
    style: block_comment
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        schema = builder.build()

        # Should build but the block_comment separator prevents spillover
        assert schema is not None
        assert "CREATE TABLE t" in schema

    def test_separator_styles_work_correctly(self, tmp_path):
        """Test each separator style generates correct format"""
        styles = {
            "block_comment": ("/*", "*/"),
            "line_comment": ("--", None),
            "mysql": ("#", None),
        }

        for style, (open_marker, close_marker) in styles.items():
            schema_dir = tmp_path / "db" / "schema" / style
            schema_dir.mkdir(parents=True, exist_ok=True)

            (schema_dir / "01_schema.sql").write_text(
                "-- Table: users\nCREATE TABLE users (id INT);"
            )

            env_config_dir = tmp_path / "db" / "environments"
            env_config_dir.mkdir(parents=True, exist_ok=True)
            (env_config_dir / "local.yaml").write_text(
                f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []

build:
  separators:
    style: {style}
"""
            )

            builder = SchemaBuilder(env="local", project_dir=tmp_path)
            schema = builder.build()

            # Check for correct separator markers
            assert open_marker in schema, f"Missing {open_marker} for style {style}"
            if close_marker:
                assert close_marker in schema, f"Missing {close_marker} for style {style}"

    def test_configuration_priority(self, tmp_path):
        """Test that configuration options override defaults"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        (schema_dir / "01_schema.sql").write_text("CREATE TABLE t (id INT);")

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
  validate_comments:
    enabled: false
  separators:
    style: line_comment
  lint:
    enabled: false
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        # Check that configuration is respected
        assert builder.env_config.build.validate_comments.enabled is False
        assert builder.env_config.build.separators.style == "line_comment"
        assert builder.env_config.build.lint.enabled is False

        schema = builder.build()
        # Should use line comment style, not block comment
        assert "--" in schema


class TestErrorMessages:
    """Test error message quality and clarity"""

    def test_comment_error_includes_file_and_line(self, tmp_path):
        """Test comment validation error includes helpful info"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        (schema_dir / "10_tables").mkdir(parents=True)
        (schema_dir / "10_tables" / "users.sql").write_text("SELECT 1;\n/* unclosed")

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
  validate_comments:
    enabled: true
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        with pytest.raises(SchemaError) as exc_info:
            builder.build()

        error = str(exc_info.value)
        # Should mention the file
        assert "users.sql" in error or "10_tables" in error
        # Should mention it's a validation error
        assert "comment" in error.lower() or "unclosed" in error.lower()

    def test_separator_error_on_invalid_style(self, tmp_path):
        """Test clear error on invalid separator style"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_schema.sql").write_text("CREATE TABLE t (id INT);")

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
  separators:
    style: invalid_style
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        with pytest.raises(SchemaError) as exc_info:
            builder.build()

        error = str(exc_info.value)
        assert "invalid" in error.lower() or "separator" in error.lower()


class TestBackwardCompatibility:
    """Test backward compatibility with existing builds"""

    def test_default_configuration_is_safe(self, tmp_path):
        """Test defaults are safe for backward compatibility"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_schema.sql").write_text("CREATE TABLE t (id INT);")

        env_config_dir = tmp_path / "db" / "environments"
        env_config_dir.mkdir(parents=True)
        # Minimal config, no validation section
        (env_config_dir / "local.yaml").write_text(
            f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        # Should build successfully with safe defaults
        schema = builder.build()
        assert schema is not None
        # Should use block_comment separators (safer default)
        assert "/*" in schema
        assert "*/" in schema

    def test_comment_validation_default_enabled(self, tmp_path):
        """Test comment validation is enabled by default"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_schema.sql").write_text("/* unclosed")

        env_config_dir = tmp_path / "db" / "environments"
        env_config_dir.mkdir(parents=True)
        # Config without explicit validate_comments
        (env_config_dir / "local.yaml").write_text(
            f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        # Should fail because comment validation is enabled by default
        with pytest.raises(SchemaError):
            builder.build()

    def test_linting_disabled_by_default(self, tmp_path):
        """Test linting doesn't affect builds by default"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        # Poor schema (would fail linting if enabled)
        (schema_dir / "01_schema.sql").write_text("CREATE TABLE t (id INT);")

        env_config_dir = tmp_path / "db" / "environments"
        env_config_dir.mkdir(parents=True)
        # Config without explicit lint section
        (env_config_dir / "local.yaml").write_text(
            f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        # Should build successfully (linting disabled by default)
        schema = builder.build()
        assert schema is not None


class TestIntegrationScenarios:
    """Test realistic integration scenarios"""

    def test_multi_file_build_with_all_features(self, tmp_path):
        """Test building multiple files with all features"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        files = {
            "01_extensions.sql": "-- Extensions\nCREATE EXTENSION IF NOT EXISTS uuid-ossp;",
            "02_types.sql": "-- Custom types\nCREATE TYPE user_role AS ENUM ('admin', 'user');",
            "03_tables.sql": """
-- Tables
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    /* User email - unique */
    email VARCHAR(255) UNIQUE NOT NULL
);

CREATE TABLE posts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    /* Post content */
    content TEXT
);
""",
            "04_indexes.sql": """
-- Indexes
CREATE INDEX idx_posts_user_id ON posts(user_id);
CREATE INDEX idx_users_email ON users(email);
""",
        }

        for fname, content in files.items():
            (schema_dir / fname).write_text(content)

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
    fail_on_spillover: true
  separators:
    style: block_comment
  lint:
    enabled: false
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        schema = builder.build()

        # Should include all files
        assert "CREATE EXTENSION" in schema
        assert "CREATE TYPE user_role" in schema
        assert "CREATE TABLE users" in schema
        assert "CREATE TABLE posts" in schema
        assert "CREATE INDEX" in schema

        # Should have block comment separators between files
        assert schema.count("/*") >= 4  # At least one separator per file
        assert schema.count("*/") >= 4

        # Should have proper structure
        assert "01_extensions" in schema
        assert "02_types" in schema
        assert "03_tables" in schema
        assert "04_indexes" in schema

    def test_environment_specific_configuration(self, tmp_path):
        """Test different environments can have different configurations"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_schema.sql").write_text("CREATE TABLE t (id INT);")

        env_config_dir = tmp_path / "db" / "environments"
        env_config_dir.mkdir(parents=True)

        # Local: strict validation
        (env_config_dir / "local.yaml").write_text(
            f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []

build:
  validate_comments:
    enabled: true
  separators:
    style: block_comment
  lint:
    enabled: true
"""
        )

        # Production: relaxed (trust CI/CD)
        (env_config_dir / "production.yaml").write_text(
            f"""
name: production
database_url: "postgresql://prod-host/db"
include_dirs:
  - {schema_dir}
exclude_dirs: []

build:
  validate_comments:
    enabled: false
  separators:
    style: line_comment
  lint:
    enabled: false
"""
        )

        # Both should work
        builder_local = SchemaBuilder(env="local", project_dir=tmp_path)
        builder_prod = SchemaBuilder(env="production", project_dir=tmp_path)

        schema_local = builder_local.build()
        schema_prod = builder_prod.build()

        assert schema_local is not None
        assert schema_prod is not None

        # Different separator styles
        assert "/*" in schema_local  # block_comment
        assert "--" in schema_prod   # line_comment
