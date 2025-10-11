"""Migration file generator from schema diffs.

This module generates Python migration files from SchemaDiff objects.
Each migration file contains up() and down() methods with the necessary SQL.
"""

from datetime import datetime
from pathlib import Path

from confiture.models.schema import SchemaChange, SchemaDiff


class MigrationGenerator:
    """Generates Python migration files from schema diffs.

    Example:
        >>> generator = MigrationGenerator(migrations_dir=Path("db/migrations"))
        >>> diff = SchemaDiff(changes=[...])
        >>> migration_file = generator.generate(diff, name="add_users_table")
    """

    def __init__(self, migrations_dir: Path):
        """Initialize migration generator.

        Args:
            migrations_dir: Directory where migration files will be created
        """
        self.migrations_dir = migrations_dir

    def generate(self, diff: SchemaDiff, name: str) -> Path:
        """Generate migration file from schema diff.

        Args:
            diff: Schema diff containing changes
            name: Name for the migration (snake_case)

        Returns:
            Path to generated migration file

        Raises:
            ValueError: If diff has no changes
        """
        if not diff.has_changes():
            raise ValueError("No changes to generate migration from")

        # Get next version number
        version = self._get_next_version()

        # Generate file path
        filename = f"{version}_{name}.py"
        filepath = self.migrations_dir / filename

        # Generate migration code
        code = self._generate_migration_code(diff, version, name)

        # Write file
        filepath.write_text(code)

        return filepath

    def _get_next_version(self) -> str:
        """Get next sequential migration version number.

        Returns:
            Version string (e.g., "001", "002", etc.)
        """
        if not self.migrations_dir.exists():
            return "001"

        # Find existing migration files
        migration_files = sorted(self.migrations_dir.glob("*.py"))

        if not migration_files:
            return "001"

        # Extract version from last file (e.g., "003_name.py" -> 3)
        last_file = migration_files[-1]
        last_version_str = last_file.name.split("_")[0]

        try:
            last_version = int(last_version_str)
            next_version = last_version + 1
            return f"{next_version:03d}"
        except ValueError:
            # If we can't parse version, start over
            return "001"

    def _generate_migration_code(self, diff: SchemaDiff, version: str, name: str) -> str:
        """Generate Python migration code.

        Args:
            diff: Schema diff containing changes
            version: Version number
            name: Migration name

        Returns:
            Python code as string
        """
        class_name = self._to_class_name(name)
        timestamp = datetime.now().isoformat()

        # Generate up and down statements
        up_statements = self._generate_up_statements(diff.changes)
        down_statements = self._generate_down_statements(diff.changes)

        template = '''"""Migration: {name}

Version: {version}
Generated: {timestamp}
"""

from confiture.models.migration import Migration


class {class_name}(Migration):
    """Migration: {name}."""

    version = "{version}"
    name = "{name}"

    def up(self) -> None:
        """Apply migration."""
{up_statements}

    def down(self) -> None:
        """Rollback migration."""
{down_statements}
'''

        return template.format(
            name=name,
            version=version,
            class_name=class_name,
            up_statements=up_statements,
            down_statements=down_statements,
            timestamp=timestamp,
        )

    def _to_class_name(self, snake_case: str) -> str:
        """Convert snake_case to PascalCase.

        Args:
            snake_case: String in snake_case format

        Returns:
            String in PascalCase format

        Example:
            >>> gen._to_class_name("add_users_table")
            'AddUsersTable'
        """
        words = snake_case.split("_")
        return "".join(word.capitalize() for word in words)

    def _generate_up_statements(self, changes: list[SchemaChange]) -> str:
        """Generate SQL statements for up migration.

        Args:
            changes: List of schema changes

        Returns:
            Python code with execute() calls
        """
        statements = []

        for change in changes:
            sql = self._change_to_up_sql(change)
            if sql:
                statements.append(f'        self.execute("{sql}")')

        return "\n".join(statements) if statements else "        pass  # No operations"

    def _generate_down_statements(self, changes: list[SchemaChange]) -> str:
        """Generate SQL statements for down migration.

        Args:
            changes: List of schema changes

        Returns:
            Python code with execute() calls
        """
        statements = []

        # Process changes in reverse order for rollback
        for change in reversed(changes):
            sql = self._change_to_down_sql(change)
            if sql:
                statements.append(f'        self.execute("{sql}")')

        return "\n".join(statements) if statements else "        pass  # No operations"

    def _change_to_up_sql(self, change: SchemaChange) -> str | None:
        """Convert schema change to SQL for up migration.

        Args:
            change: Schema change

        Returns:
            SQL string or None if not applicable
        """
        if change.type == "ADD_TABLE":
            # We don't have full schema info, so create a placeholder
            return f"# TODO: ADD_TABLE {change.table}"

        elif change.type == "DROP_TABLE":
            return f"DROP TABLE {change.table}"

        elif change.type == "RENAME_TABLE":
            return f"ALTER TABLE {change.old_value} RENAME TO {change.new_value}"

        elif change.type == "ADD_COLUMN":
            # For ADD_COLUMN, we might have type info in new_value
            col_def = change.new_value if change.new_value else "TEXT"
            return f"ALTER TABLE {change.table} ADD COLUMN {change.column} {col_def}"

        elif change.type == "DROP_COLUMN":
            return f"ALTER TABLE {change.table} DROP COLUMN {change.column}"

        elif change.type == "RENAME_COLUMN":
            return (
                f"ALTER TABLE {change.table} RENAME COLUMN {change.old_value} TO {change.new_value}"
            )

        elif change.type == "CHANGE_COLUMN_TYPE":
            return (
                f"ALTER TABLE {change.table} ALTER COLUMN {change.column} TYPE {change.new_value}"
            )

        elif change.type == "CHANGE_COLUMN_NULLABLE":
            if change.new_value == "false":
                return f"ALTER TABLE {change.table} ALTER COLUMN {change.column} SET NOT NULL"
            else:
                return f"ALTER TABLE {change.table} ALTER COLUMN {change.column} DROP NOT NULL"

        elif change.type == "CHANGE_COLUMN_DEFAULT":
            if change.new_value:
                return f"ALTER TABLE {change.table} ALTER COLUMN {change.column} SET DEFAULT {change.new_value}"
            else:
                return f"ALTER TABLE {change.table} ALTER COLUMN {change.column} DROP DEFAULT"

        return None

    def _change_to_down_sql(self, change: SchemaChange) -> str | None:
        """Convert schema change to SQL for down migration (reverse).

        Args:
            change: Schema change

        Returns:
            SQL string or None if not applicable
        """
        if change.type == "ADD_TABLE":
            # Reverse of ADD is DROP
            return f"DROP TABLE {change.table}"

        elif change.type == "DROP_TABLE":
            # Can't recreate without schema info
            return f"# WARNING: Cannot auto-generate down migration for DROP_TABLE {change.table}"

        elif change.type == "RENAME_TABLE":
            # Reverse the rename
            return f"ALTER TABLE {change.new_value} RENAME TO {change.old_value}"

        elif change.type == "ADD_COLUMN":
            # Reverse of ADD is DROP
            return f"ALTER TABLE {change.table} DROP COLUMN {change.column}"

        elif change.type == "DROP_COLUMN":
            # Can't recreate without schema info
            return f"# WARNING: Cannot auto-generate down migration for DROP_COLUMN {change.table}.{change.column}"

        elif change.type == "RENAME_COLUMN":
            # Reverse the rename
            return (
                f"ALTER TABLE {change.table} RENAME COLUMN {change.new_value} TO {change.old_value}"
            )

        elif change.type == "CHANGE_COLUMN_TYPE":
            # Reverse the type change
            return (
                f"ALTER TABLE {change.table} ALTER COLUMN {change.column} TYPE {change.old_value}"
            )

        elif change.type == "CHANGE_COLUMN_NULLABLE":
            # Reverse the nullable change
            if change.old_value == "false":
                return f"ALTER TABLE {change.table} ALTER COLUMN {change.column} SET NOT NULL"
            else:
                return f"ALTER TABLE {change.table} ALTER COLUMN {change.column} DROP NOT NULL"

        elif change.type == "CHANGE_COLUMN_DEFAULT":
            # Reverse the default change
            if change.old_value:
                return f"ALTER TABLE {change.table} ALTER COLUMN {change.column} SET DEFAULT {change.old_value}"
            else:
                return f"ALTER TABLE {change.table} ALTER COLUMN {change.column} DROP DEFAULT"

        return None
