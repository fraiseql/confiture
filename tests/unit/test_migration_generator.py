"""Unit tests for Migration Generator (Milestone 1.11)."""

import pytest

from confiture.core.migration_generator import MigrationGenerator
from confiture.models.schema import SchemaChange, SchemaDiff


class TestMigrationGenerator:
    """Test migration file generation from schema diffs."""

    def test_generate_migration_creates_file(self, tmp_path):
        """Should create migration file in migrations directory."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(changes=[SchemaChange(type="ADD_TABLE", table="users")])

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="add_users_table")

        assert migration_file.exists()
        assert migration_file.parent == migrations_dir
        assert "add_users_table" in migration_file.name

    def test_generate_migration_with_version_number(self, tmp_path):
        """Should generate sequential version numbers."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # First migration should be 001
        diff1 = SchemaDiff(changes=[SchemaChange(type="ADD_TABLE", table="users")])
        file1 = generator.generate(diff1, name="add_users")
        assert file1.name.startswith("001_")

        # Second migration should be 002
        diff2 = SchemaDiff(changes=[SchemaChange(type="ADD_TABLE", table="posts")])
        file2 = generator.generate(diff2, name="add_posts")
        assert file2.name.startswith("002_")

    def test_generate_migration_for_add_table(self, tmp_path):
        """Should generate correct SQL for ADD_TABLE."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(changes=[SchemaChange(type="ADD_TABLE", table="users")])

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="add_users_table")

        content = migration_file.read_text()

        # Should contain migration class
        assert "class AddUsersTable(Migration):" in content
        assert 'version = "001"' in content
        assert 'name = "add_users_table"' in content

        # Should contain up method with CREATE TABLE
        assert "def up(self) -> None:" in content
        # Note: Full table creation requires schema info, so this might be a placeholder
        assert "# TODO: ADD_TABLE users" in content or "CREATE TABLE users" in content

        # Should contain down method with DROP TABLE
        assert "def down(self) -> None:" in content
        assert 'self.execute("DROP TABLE users")' in content or "DROP TABLE users" in content

    def test_generate_migration_for_drop_table(self, tmp_path):
        """Should generate correct SQL for DROP_TABLE."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(changes=[SchemaChange(type="DROP_TABLE", table="old_table")])

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="drop_old_table")

        content = migration_file.read_text()

        # Up should drop the table
        assert "DROP TABLE old_table" in content

        # Down would need to recreate it (but we don't have the schema)
        assert (
            "# WARNING: Cannot auto-generate down migration" in content
            or "CREATE TABLE old_table" in content
        )

    def test_generate_migration_for_add_column(self, tmp_path):
        """Should generate correct SQL for ADD_COLUMN."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[
                SchemaChange(
                    type="ADD_COLUMN",
                    table="users",
                    column="email",
                    new_value="TEXT NOT NULL",  # Type info
                )
            ]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="add_user_email")

        content = migration_file.read_text()

        # Up should add column
        assert "ALTER TABLE users" in content
        assert "ADD COLUMN email" in content

        # Down should drop column
        assert "DROP COLUMN email" in content

    def test_generate_migration_for_drop_column(self, tmp_path):
        """Should generate correct SQL for DROP_COLUMN."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[
                SchemaChange(
                    type="DROP_COLUMN",
                    table="users",
                    column="old_field",
                )
            ]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="drop_old_field")

        content = migration_file.read_text()

        # Up should drop column
        assert "ALTER TABLE users" in content
        assert "DROP COLUMN old_field" in content

        # Down would need to recreate it (but we don't have the schema)
        assert (
            "# WARNING: Cannot auto-generate down migration" in content
            or "ADD COLUMN old_field" in content
        )

    def test_generate_migration_for_rename_column(self, tmp_path):
        """Should generate correct SQL for RENAME_COLUMN."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[
                SchemaChange(
                    type="RENAME_COLUMN",
                    table="users",
                    old_value="full_name",
                    new_value="display_name",
                )
            ]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="rename_user_full_name")

        content = migration_file.read_text()

        # Up should rename column
        assert "ALTER TABLE users" in content
        assert "RENAME COLUMN full_name TO display_name" in content

        # Down should rename back
        assert "RENAME COLUMN display_name TO full_name" in content

    def test_generate_migration_for_change_column_type(self, tmp_path):
        """Should generate correct SQL for CHANGE_COLUMN_TYPE."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[
                SchemaChange(
                    type="CHANGE_COLUMN_TYPE",
                    table="users",
                    column="age",
                    old_value="INTEGER",
                    new_value="BIGINT",
                )
            ]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="change_age_to_bigint")

        content = migration_file.read_text()

        # Up should change type
        assert "ALTER TABLE users" in content
        assert "ALTER COLUMN age TYPE BIGINT" in content

        # Down should change back
        assert "ALTER COLUMN age TYPE INTEGER" in content

    def test_generate_migration_for_change_nullable(self, tmp_path):
        """Should generate correct SQL for CHANGE_COLUMN_NULLABLE."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[
                SchemaChange(
                    type="CHANGE_COLUMN_NULLABLE",
                    table="users",
                    column="email",
                    old_value="true",
                    new_value="false",
                )
            ]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="make_email_not_null")

        content = migration_file.read_text()

        # Up should add NOT NULL
        assert "ALTER TABLE users" in content
        assert "ALTER COLUMN email SET NOT NULL" in content

        # Down should drop NOT NULL
        assert "ALTER COLUMN email DROP NOT NULL" in content

    def test_generate_migration_for_change_default(self, tmp_path):
        """Should generate correct SQL for CHANGE_COLUMN_DEFAULT."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[
                SchemaChange(
                    type="CHANGE_COLUMN_DEFAULT",
                    table="settings",
                    column="enabled",
                    old_value="FALSE",
                    new_value="TRUE",
                )
            ]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="change_default_enabled")

        content = migration_file.read_text()

        # Up should set new default
        assert "ALTER TABLE settings" in content
        assert "ALTER COLUMN enabled SET DEFAULT TRUE" in content

        # Down should set old default
        assert "ALTER COLUMN enabled SET DEFAULT FALSE" in content

    def test_generate_migration_with_multiple_changes(self, tmp_path):
        """Should generate migration with multiple changes."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[
                SchemaChange(type="ADD_TABLE", table="posts"),
                SchemaChange(
                    type="ADD_COLUMN",
                    table="users",
                    column="email",
                ),
                SchemaChange(
                    type="RENAME_COLUMN",
                    table="users",
                    old_value="name",
                    new_value="username",
                ),
            ]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="multiple_changes")

        content = migration_file.read_text()

        # Should contain all changes
        assert "posts" in content
        assert "ADD COLUMN email" in content
        assert "RENAME COLUMN name TO username" in content

    def test_generate_migration_empty_diff(self, tmp_path):
        """Should handle empty diff gracefully."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(changes=[])

        generator = MigrationGenerator(migrations_dir=migrations_dir)

        with pytest.raises(ValueError, match="No changes to generate"):
            generator.generate(diff, name="empty")

    def test_migration_file_is_valid_python(self, tmp_path):
        """Generated migration file should be valid Python."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(
            changes=[
                SchemaChange(
                    type="RENAME_COLUMN",
                    table="users",
                    old_value="name",
                    new_value="username",
                )
            ]
        )

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="test_migration")

        # Try to compile the file
        content = migration_file.read_text()
        compile(content, str(migration_file), "exec")  # Should not raise

    def test_get_next_version_empty_dir(self, tmp_path):
        """Should return 001 for empty migrations directory."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        version = generator._get_next_version()

        assert version == "001"

    def test_get_next_version_with_existing(self, tmp_path):
        """Should return next version number."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create existing migrations
        (migrations_dir / "001_first.py").touch()
        (migrations_dir / "002_second.py").touch()

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        version = generator._get_next_version()

        assert version == "003"

    def test_to_class_name_conversion(self, tmp_path):
        """Should convert snake_case to PascalCase."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        diff = SchemaDiff(changes=[SchemaChange(type="ADD_TABLE", table="users")])

        generator = MigrationGenerator(migrations_dir=migrations_dir)
        migration_file = generator.generate(diff, name="add_users_table")

        content = migration_file.read_text()

        # Should have PascalCase class name
        assert "class AddUsersTable(Migration):" in content
