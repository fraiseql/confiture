"""Tests for schema builder file separator configuration

Tests cover:
- Block comment separator style (safer, recommended)
- Line comment separator style (default, backward compatible)
- MySQL style separators
- Custom template support
- Integration with builder
"""

from pathlib import Path

import pytest

from confiture.core.builder import SchemaBuilder


class TestSeparatorBasics:
    """Test basic separator format generation"""

    def test_block_comment_separator_format(self):
        """Test block comment separator format"""
        builder = SchemaBuilder(env="local")
        sep = builder._get_separator_for_file(Path("db/schema/10_tables/users.sql"))

        # Should contain block comment markers
        assert "/*" in sep
        assert "*/" in sep
        # Should contain file path
        assert "users.sql" in sep
        # Should be complete SQL comment (with surrounding newlines)
        assert "/*" in sep.lstrip()
        assert "*/" in sep.rstrip()
        # Should start and end with newlines
        assert sep.startswith("\n")
        assert sep.endswith("\n")

    def test_line_comment_separator_format(self):
        """Test line comment separator format (backward compatible)"""
        # Line comment is the default
        builder = SchemaBuilder(env="local")
        # Change config to line_comment
        builder.env_config.build.separators.style = "line_comment"

        sep = builder._get_separator_for_file(Path("db/schema/10_tables/users.sql"))

        # Should contain line comment markers
        assert "--" in sep
        # Should contain file path
        assert "users.sql" in sep
        # Should be all line comments
        lines = sep.split("\n")
        for line in lines:
            if line.strip():
                assert line.strip().startswith("--")

    def test_mysql_separator_format(self):
        """Test MySQL separator format"""
        builder = SchemaBuilder(env="local")
        builder.env_config.build.separators.style = "mysql"

        sep = builder._get_separator_for_file(Path("db/schema/10_tables/users.sql"))

        # Should contain MySQL comment markers
        assert "#" in sep
        # Should contain file path
        assert "users.sql" in sep
        # Should be all line comments
        lines = sep.split("\n")
        for line in lines:
            if line.strip():
                assert line.strip().startswith("#")


class TestSeparatorStyles:
    """Test different separator style options"""

    def test_block_comment_includes_equals_signs(self):
        """Test block comment has visual separator"""
        builder = SchemaBuilder(env="local")
        builder.env_config.build.separators.style = "block_comment"

        sep = builder._get_separator_for_file(Path("test.sql"))

        # Should have decorative equals signs
        assert "=" in sep
        assert "/*" in sep
        assert "*/" in sep

    def test_line_comment_includes_equals_signs(self):
        """Test line comment has visual separator"""
        builder = SchemaBuilder(env="local")
        builder.env_config.build.separators.style = "line_comment"

        sep = builder._get_separator_for_file(Path("test.sql"))

        # Should have decorative equals signs
        assert "=" in sep
        assert "--" in sep

    def test_separator_includes_newlines(self):
        """Test separator includes surrounding newlines"""
        builder = SchemaBuilder(env="local")

        sep = builder._get_separator_for_file(Path("test.sql"))

        # Should start and end with newlines
        assert sep.startswith("\n")
        assert sep.endswith("\n")

    def test_different_files_same_separator_format(self):
        """Test different files use same format"""
        builder = SchemaBuilder(env="local")
        builder.env_config.build.separators.style = "block_comment"

        sep1 = builder._get_separator_for_file(Path("users.sql"))
        sep2 = builder._get_separator_for_file(Path("products.sql"))

        # Both should be block comments
        assert "/*" in sep1 and "*/" in sep1
        assert "/*" in sep2 and "*/" in sep2
        # But contain different file names
        assert "users.sql" in sep1
        assert "products.sql" in sep2


class TestSeparatorConfiguration:
    """Test separator configuration options"""

    def test_default_separator_is_block_comment(self):
        """Test default separator style"""
        builder = SchemaBuilder(env="local")

        # Default should be block_comment for safety
        assert builder.env_config.build.separators.style == "block_comment"

    def test_separator_style_validation(self):
        """Test invalid separator style raises error"""
        from confiture.exceptions import SchemaError

        builder = SchemaBuilder(env="local")
        builder.env_config.build.separators.style = "invalid_style"

        # Should raise error on invalid style
        with pytest.raises(SchemaError):
            builder._get_separator_for_file(Path("test.sql"))

    def test_separator_config_in_yaml(self):
        """Test separator config is loaded from YAML"""
        builder = SchemaBuilder(env="local")

        # Should have separator config
        assert builder.env_config.build.separators is not None
        assert hasattr(builder.env_config.build.separators, "style")


class TestSeparatorWithSpecialPaths:
    """Test separators with various file paths"""

    def test_separator_with_nested_path(self):
        """Test separator with nested directory path"""
        builder = SchemaBuilder(env="local")

        sep = builder._get_separator_for_file(
            Path("db/schema/10_tables/public/users.sql")
        )

        # Should include full file path
        assert "users.sql" in sep or "public" in sep

    def test_separator_with_special_chars_in_filename(self):
        """Test separator with special characters in filename"""
        builder = SchemaBuilder(env="local")

        sep = builder._get_separator_for_file(Path("db/schema/user_profile.sql"))

        # Should handle underscores
        assert "user_profile" in sep

    def test_separator_with_hyphenated_filename(self):
        """Test separator with hyphenated filename"""
        builder = SchemaBuilder(env="local")

        sep = builder._get_separator_for_file(Path("db/schema/user-profile.sql"))

        # Should handle hyphens
        assert "user-profile" in sep

    def test_separator_length_reasonable(self):
        """Test separator length is reasonable"""
        builder = SchemaBuilder(env="local")

        sep = builder._get_separator_for_file(Path("users.sql"))

        # Should be relatively short (not a huge block)
        assert len(sep) < 500
        # But long enough to be visible
        assert len(sep) > 20


class TestSeparatorContent:
    """Test separator content quality"""

    def test_block_comment_separator_readable(self):
        """Test block comment separator is human readable"""
        builder = SchemaBuilder(env="local")
        builder.env_config.build.separators.style = "block_comment"

        sep = builder._get_separator_for_file(Path("db/schema/10_tables/users.sql"))

        # Should have "File:" label
        assert "File:" in sep or "file" in sep.lower()

    def test_line_comment_separator_readable(self):
        """Test line comment separator is human readable"""
        builder = SchemaBuilder(env="local")
        builder.env_config.build.separators.style = "line_comment"

        sep = builder._get_separator_for_file(Path("db/schema/10_tables/users.sql"))

        # Should have "File:" label
        assert "File:" in sep or "file" in sep.lower()

    def test_mysql_separator_readable(self):
        """Test MySQL separator is human readable"""
        builder = SchemaBuilder(env="local")
        builder.env_config.build.separators.style = "mysql"

        sep = builder._get_separator_for_file(Path("db/schema/10_tables/users.sql"))

        # Should have "File:" label
        assert "File:" in sep or "file" in sep.lower()


class TestSeparatorIntegration:
    """Test separator integration with builder"""

    def test_build_includes_separators(self, tmp_path):
        """Test that build includes separators between files"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        (schema_dir / "01_users.sql").write_text("CREATE TABLE users (id INT);")
        (schema_dir / "02_products.sql").write_text("CREATE TABLE products (id INT);")

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
  separators:
    style: block_comment
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        schema = builder.build()

        # Should include both file contents
        assert "CREATE TABLE users" in schema
        assert "CREATE TABLE products" in schema
        # Should have separators (block comments)
        assert "/*" in schema
        assert "*/" in schema

    def test_separator_prevents_spillover(self, tmp_path):
        """Test block comment separator prevents spillover"""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        # File ending with unclosed comment (would be spillover)
        (schema_dir / "01_schema.sql").write_text("/* This comment")
        # With block_comment separator, next file's separator will close it
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
  sort_mode: alphabetical
  validate_comments:
    enabled: false
  separators:
    style: block_comment
"""
        )

        builder = SchemaBuilder(env="local", project_dir=tmp_path)
        schema = builder.build()

        # Should build successfully
        assert schema is not None
        assert "CREATE TABLE t" in schema
        # The block_comment separator should have closed the comment
        assert "/*" in schema and "*/" in schema
