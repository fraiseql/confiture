"""Tests for confiture package __init__ and lazy loading."""

import pytest


class TestPackageMetadata:
    """Test package metadata."""

    def test_version_exists(self):
        """Test that __version__ is defined."""
        from confiture import __version__

        assert __version__ is not None
        assert isinstance(__version__, str)
        assert "0.2.0" in __version__

    def test_author_exists(self):
        """Test that __author__ is defined."""
        from confiture import __author__

        assert __author__ is not None
        assert isinstance(__author__, str)

    def test_email_exists(self):
        """Test that __email__ is defined."""
        from confiture import __email__

        assert __email__ is not None
        assert isinstance(__email__, str)
        assert "@" in __email__


class TestLazyImports:
    """Test lazy loading of components."""

    def test_lazy_import_schema_builder(self):
        """Test lazy importing SchemaBuilder."""
        import confiture

        # Should lazy load SchemaBuilder
        SchemaBuilder = confiture.SchemaBuilder
        assert SchemaBuilder is not None
        assert SchemaBuilder.__name__ == "SchemaBuilder"

    def test_lazy_import_migrator(self):
        """Test lazy importing Migrator."""
        import confiture

        # Should lazy load Migrator
        Migrator = confiture.Migrator
        assert Migrator is not None
        assert Migrator.__name__ == "Migrator"

    def test_lazy_import_environment(self):
        """Test lazy importing Environment."""
        import confiture

        # Should lazy load Environment
        Environment = confiture.Environment
        assert Environment is not None
        assert Environment.__name__ == "Environment"

    def test_lazy_import_invalid_attribute(self):
        """Test that invalid attributes raise AttributeError."""
        import confiture

        with pytest.raises(AttributeError, match="has no attribute 'InvalidClass'"):
            _ = confiture.InvalidClass

    def test_lazy_import_preserves_functionality(self):
        """Test that lazy-loaded classes work correctly."""
        import tempfile
        from pathlib import Path

        from confiture import Environment

        # Create temporary config
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create schema directory that config references
            schema_dir = Path(tmpdir) / "db" / "schema"
            schema_dir.mkdir(parents=True)

            config_dir = Path(tmpdir) / "db" / "environments"
            config_dir.mkdir(parents=True)
            config_file = config_dir / "test.yaml"
            config_file.write_text(f"""
name: test
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

            # Should be able to use lazy-loaded class
            env = Environment.load("test", project_dir=Path(tmpdir))
            assert env.name == "test"


class TestPackageAll:
    """Test __all__ exports."""

    def test_all_exports_metadata(self):
        """Test that __all__ includes metadata."""
        import confiture

        assert "__version__" in confiture.__all__
        assert "__author__" in confiture.__all__
        assert "__email__" in confiture.__all__

    def test_all_is_list(self):
        """Test that __all__ is a list."""
        import confiture

        assert isinstance(confiture.__all__, list)

    def test_can_import_from_all(self):
        """Test that items in __all__ can be imported."""
        from confiture import __author__, __email__, __version__

        assert __version__ is not None
        assert __author__ is not None
        assert __email__ is not None
