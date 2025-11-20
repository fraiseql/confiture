# tests/unit/test_strict_mode.py

from unittest.mock import MagicMock

from confiture.models.migration import Migration


class TestStrictMode:
    """Test strict mode for error handling"""

    def test_migration_strict_mode_attribute_defaults_to_false(self):
        """Migration strict_mode should default to False"""
        mock_conn = MagicMock()

        class TestMigration(Migration):
            version = "001"
            name = "test"

            def up(self):
                pass

            def down(self):
                pass

        migration = TestMigration(connection=mock_conn)
        assert migration.strict_mode is False

    def test_migration_can_enable_strict_mode(self):
        """Migration can override strict_mode to True"""
        mock_conn = MagicMock()

        class StrictMigration(Migration):
            version = "001"
            name = "test"
            strict_mode = True

            def up(self):
                pass

            def down(self):
                pass

        migration = StrictMigration(connection=mock_conn)
        # Class attribute should be accessible
        assert migration.strict_mode is True

    def test_strict_mode_enabled_detects_warnings(self, test_db_connection):
        """Strict mode should detect and report PostgreSQL warnings"""

        class WarningMigration(Migration):
            version = "001"
            name = "test_warning"
            strict_mode = True

            def up(self):
                # This creates a notice/warning but doesn't fail
                self.execute("DO $$ BEGIN RAISE NOTICE 'Test notice'; END $$;")

            def down(self):
                pass

        migration = WarningMigration(connection=test_db_connection)

        # In strict mode, should detect notices and potentially fail
        # For now, this test documents the intended behavior
        # The actual implementation will depend on how we detect warnings
        migration.up()  # Should succeed for now, but could be enhanced

    def test_normal_mode_ignores_notices(self, test_db_connection):
        """Normal mode should ignore PostgreSQL notices"""

        class NoticeMigration(Migration):
            version = "002"
            name = "test_notice"
            # strict_mode = False (default)

            def up(self):
                # Generate a notice
                self.execute("DO $$ BEGIN RAISE NOTICE 'Test notice'; END $$;")
                # This should succeed without issues

            def down(self):
                pass

        migration = NoticeMigration(connection=test_db_connection)

        # Should succeed without raising error
        migration.up()  # No exception expected

    def test_cli_strict_flag_enables_strict_mode(self):
        """CLI --strict flag should enable strict mode on migrations"""
        # This test would verify CLI integration
        # For now, it's a placeholder for the CLI test
        pass

    def test_config_strict_mode_enables_strict_mode(self, tmp_path):
        """Configuration file strict_mode should enable strict mode on migrations"""
        from confiture.config.environment import Environment

        # Create directory structure
        db_dir = tmp_path / "db"
        env_dir = db_dir / "environments"
        schema_dir = db_dir / "schema"
        env_dir.mkdir(parents=True)
        schema_dir.mkdir()

        # Create a test config with strict_mode enabled
        config_path = env_dir / "test.yaml"
        config_path.write_text("""
name: test
database_url: postgresql://localhost/test
include_dirs:
  - db/schema
migration:
  strict_mode: true
""")

        # Load the config
        env = Environment.load("test", project_dir=tmp_path)

        # Verify strict_mode is set
        assert env.migration.strict_mode is True

    def test_config_strict_mode_defaults_to_false(self, tmp_path):
        """Configuration file should default strict_mode to False"""
        from confiture.config.environment import Environment

        # Create directory structure
        db_dir = tmp_path / "db"
        env_dir = db_dir / "environments"
        schema_dir = db_dir / "schema"
        env_dir.mkdir(parents=True)
        schema_dir.mkdir()

        # Create a test config without migration settings
        config_path = env_dir / "test.yaml"
        config_path.write_text("""
name: test
database_url: postgresql://localhost/test
include_dirs:
  - db/schema
""")

        # Load the config
        env = Environment.load("test", project_dir=tmp_path)

        # Verify strict_mode defaults to False
        assert env.migration.strict_mode is False
