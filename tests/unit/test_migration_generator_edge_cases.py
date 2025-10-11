"""Edge case tests for MigrationGenerator to improve coverage."""


from confiture.core.migration_generator import MigrationGenerator
from confiture.models.schema import SchemaChange, SchemaDiff


class TestMigrationGeneratorEdgeCases:
    """Test edge cases in MigrationGenerator."""

    def test_generate_with_existing_directory(self, tmp_path):
        """Test that generate works when migrations directory exists."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)  # Create first

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        diff = SchemaDiff(
            changes=[SchemaChange(type="ADD_TABLE", table="users")]
        )

        migration_file = generator.generate(diff=diff, name="add_users")

        # File should be created
        assert migrations_dir.exists()
        assert migration_file.parent == migrations_dir
        assert migration_file.exists()

    def test_to_class_name_edge_cases(self, tmp_path):
        """Test _to_class_name with various input formats."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Test various name formats
        assert generator._to_class_name("add_users") == "AddUsers"
        assert generator._to_class_name("add_user_email") == "AddUserEmail"
        assert generator._to_class_name("add") == "Add"
        assert generator._to_class_name("ADD_USERS") == "AddUsers"

    def test_change_to_up_sql_all_types(self, tmp_path):
        """Test _change_to_up_sql for all change types."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Test ADD_COLUMN
        change = SchemaChange(type="ADD_COLUMN", table="users", column="email")
        sql = generator._change_to_up_sql(change)
        assert "ALTER TABLE users" in sql
        assert "ADD COLUMN email" in sql

        # Test DROP_COLUMN
        change = SchemaChange(type="DROP_COLUMN", table="users", column="old_field")
        sql = generator._change_to_up_sql(change)
        assert "ALTER TABLE users" in sql
        assert "DROP COLUMN old_field" in sql

        # Test RENAME_COLUMN
        change = SchemaChange(
            type="RENAME_COLUMN",
            table="users",
            old_value="full_name",
            new_value="display_name",
        )
        sql = generator._change_to_up_sql(change)
        assert "ALTER TABLE users" in sql
        assert "RENAME COLUMN full_name TO display_name" in sql

        # Test CHANGE_COLUMN_TYPE
        change = SchemaChange(
            type="CHANGE_COLUMN_TYPE",
            table="users",
            column="age",
            new_value="BIGINT",
        )
        sql = generator._change_to_up_sql(change)
        assert "ALTER TABLE users" in sql
        assert "ALTER COLUMN age TYPE BIGINT" in sql

        # Test DROP_TABLE
        change = SchemaChange(type="DROP_TABLE", table="old_table")
        sql = generator._change_to_up_sql(change)
        assert "DROP TABLE old_table" in sql

    def test_change_to_down_sql_all_types(self, tmp_path):
        """Test _change_to_down_sql for all change types."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Test ADD_COLUMN (reverse is DROP)
        change = SchemaChange(type="ADD_COLUMN", table="users", column="email")
        sql = generator._change_to_down_sql(change)
        assert "DROP COLUMN email" in sql

        # Test DROP_COLUMN (reverse is ADD - warning)
        change = SchemaChange(type="DROP_COLUMN", table="users", column="old_field")
        sql = generator._change_to_down_sql(change)
        assert "WARNING" in sql or "Add back column manually" in sql

        # Test RENAME_COLUMN (reverse names)
        change = SchemaChange(
            type="RENAME_COLUMN",
            table="users",
            old_value="full_name",
            new_value="display_name",
        )
        sql = generator._change_to_down_sql(change)
        assert "RENAME COLUMN display_name TO full_name" in sql

        # Test DROP_TABLE (reverse is warning)
        change = SchemaChange(type="DROP_TABLE", table="old_table")
        sql = generator._change_to_down_sql(change)
        assert "WARNING" in sql or "Recreate table manually" in sql

    def test_generate_migration_with_complex_diff(self, tmp_path):
        """Test generating migration with multiple complex changes."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Complex diff with multiple changes
        diff = SchemaDiff(
            changes=[
                SchemaChange(type="ADD_TABLE", table="users"),
                SchemaChange(type="ADD_COLUMN", table="posts", column="title"),
                SchemaChange(
                    type="RENAME_COLUMN",
                    table="users",
                    old_value="name",
                    new_value="full_name",
                ),
                SchemaChange(type="DROP_TABLE", table="old_logs"),
            ]
        )

        migration_file = generator.generate(diff=diff, name="complex_changes")

        # Should create file
        assert migration_file.exists()

        # Read content
        content = migration_file.read_text()

        # Should contain all change types
        assert "TODO: ADD_TABLE users" in content  # ADD_TABLE generates TODO
        assert "ADD COLUMN title" in content
        assert "RENAME COLUMN" in content
        assert "DROP TABLE old_logs" in content

    def test_get_next_version_with_gaps(self, tmp_path):
        """Test _get_next_version with gaps in version sequence."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create migrations with gaps
        (migrations_dir / "001_first.py").write_text("# migration")
        (migrations_dir / "003_third.py").write_text("# migration")  # Gap at 002
        (migrations_dir / "005_fifth.py").write_text("# migration")  # Gap at 004

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Should find next version after highest (005 -> 006)
        next_version = generator._get_next_version()
        assert next_version == "006"

    def test_get_next_version_empty_directory(self, tmp_path):
        """Test _get_next_version with no existing migrations."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Should start at 001
        next_version = generator._get_next_version()
        assert next_version == "001"
