"""Tests for builder integration with SQL linting

Tests that SchemaBuilder properly runs schema linting during build process.
"""

from confiture.core.builder import SchemaBuilder


class TestBuilderLinting:
    """Test SchemaBuilder integration with SQL linting"""

    def test_linting_disabled_by_default(self, tmp_path):
        """Test that linting is disabled by default"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # Poor schema without docstring (would fail linting)
        (schema_dir / "01_tables.sql").write_text("CREATE TABLE users (id INT PRIMARY KEY);")

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
  lint:
    enabled: false
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        # Should build without error despite linting issues
        schema = builder.build()
        assert schema is not None

    def test_linting_can_be_enabled(self, tmp_path):
        """Test that linting can be enabled"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # Good schema with documentation
        (schema_dir / "01_tables.sql").write_text(
            """
-- Table: users
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL
);

-- Index on users.name
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
  lint:
    enabled: true
    fail_on_error: true
    fail_on_warning: false
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        # Should build successfully with proper schema
        schema = builder.build()
        assert schema is not None
        assert "CREATE TABLE users" in schema

    def test_linting_config_options(self, tmp_path):
        """Test linting configuration options are accessible"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_tables.sql").write_text("CREATE TABLE t (id INT);")

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
  lint:
    enabled: true
    fail_on_error: false
    fail_on_warning: true
    rules:
      - naming_convention
      - documentation
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)

        # Check that linting config is accessible
        assert builder.env_config.build.lint is not None
        assert builder.env_config.build.lint.enabled is True
        assert builder.env_config.build.lint.fail_on_error is False
        assert builder.env_config.build.lint.fail_on_warning is True
        assert "naming_convention" in builder.env_config.build.lint.rules

    def test_linting_default_configuration(self, tmp_path):
        """Test default linting configuration"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_tables.sql").write_text("CREATE TABLE t (id INT);")

        env_config_dir = tmp_path / "db" / "environments"
        env_config_dir.mkdir(parents=True)
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

        # Check defaults
        assert builder.env_config.build.lint.enabled is False
        assert builder.env_config.build.lint.fail_on_error is True
        assert builder.env_config.build.lint.fail_on_warning is False

    def test_build_with_linting_disabled(self, tmp_path):
        """Test build proceeds when linting is disabled"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_tables.sql").write_text("CREATE TABLE users (id INT);")

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
  lint:
    enabled: false
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        schema = builder.build()

        assert schema is not None
        assert len(schema) > 0
        assert "CREATE TABLE users" in schema

    def test_linting_configuration_in_environment(self, tmp_path):
        """Test linting configuration is properly loaded from environment"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_schema.sql").write_text("CREATE TABLE x (id INT);")

        env_config_dir = tmp_path / "db" / "environments"
        env_config_dir.mkdir(parents=True)

        # Create environment with specific linting rules
        (env_config_dir / "local.yaml").write_text(
            f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []

build:
  lint:
    enabled: true
    fail_on_error: true
    fail_on_warning: false
    rules:
      - naming_convention
      - primary_key
      - documentation
      - missing_index
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        lint_config = builder.env_config.build.lint

        # Verify all config options are loaded
        assert lint_config.enabled is True
        assert lint_config.fail_on_error is True
        assert lint_config.fail_on_warning is False
        assert len(lint_config.rules) == 4
        assert "naming_convention" in lint_config.rules
        assert "primary_key" in lint_config.rules
        assert "documentation" in lint_config.rules
        assert "missing_index" in lint_config.rules


class TestBuilderLintingBehavior:
    """Test builder linting behavior during build"""

    def test_build_completes_with_linting_disabled(self, tmp_path):
        """Test build works with linting disabled"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        files = ["01_users", "02_products", "03_orders"]
        for fname in files:
            (schema_dir / f"{fname}.sql").write_text(f"-- {fname}\nCREATE TABLE {fname} (id INT);")

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
  lint:
    enabled: false
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        schema = builder.build()

        # Should include all files
        for fname in files:
            assert fname in schema

    def test_build_output_not_affected_by_linting_disabled(self, tmp_path):
        """Test schema output is identical whether linting is enabled/disabled"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_schema.sql").write_text(
            """
CREATE TABLE users (
    id INT PRIMARY KEY,
    name VARCHAR(255)
);
"""
        )

        # Build with linting disabled
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
  lint:
    enabled: false
"""
        )

        builder1 = SchemaBuilder(env="local", project_dir=tmp_path)
        schema1 = builder1.build()

        # Update to enable linting
        (env_config_dir / "local.yaml").write_text(
            f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
exclude_dirs: []

build:
  lint:
    enabled: true
    fail_on_error: false
    fail_on_warning: false
"""
        )

        builder2 = SchemaBuilder(env="local", project_dir=tmp_path)
        schema2 = builder2.build()

        # Core SQL should be the same (linting shouldn't modify it)
        # Extract SQL content (skip header with timestamp)
        sql1 = "\n".join(
            [line for line in schema1.split("\n") if not line.startswith("--") or "CREATE" in line]
        )
        sql2 = "\n".join(
            [line for line in schema2.split("\n") if not line.startswith("--") or "CREATE" in line]
        )
        assert sql1 == sql2
        # Both should contain the table definition
        assert "CREATE TABLE users" in schema1
        assert "CREATE TABLE users" in schema2
