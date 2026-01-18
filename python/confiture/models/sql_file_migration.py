"""SQL file-based migrations.

Provides support for pure SQL migration files without Python boilerplate.
Migrations are discovered from .up.sql/.down.sql file pairs.

Example file structure:
    db/migrations/
    ├── 001_create_users.py           # Python migration
    ├── 002_add_posts.py              # Python migration
    ├── 003_move_catalog_tables.up.sql    # SQL migration (up)
    ├── 003_move_catalog_tables.down.sql  # SQL migration (down)

The migrator will automatically detect and load SQL file pairs alongside
Python migrations.
"""

from pathlib import Path

import psycopg

from confiture.models.migration import Migration


class FileSQLMigration(Migration):
    """Migration loaded from .up.sql/.down.sql file pair.

    This class is instantiated dynamically by the migrator when it discovers
    SQL file pairs. Users don't create these directly - they just create the
    SQL files.

    The version and name are extracted from the filename:
    - `003_move_catalog_tables.up.sql` → version="003", name="move_catalog_tables"

    Attributes:
        up_file: Path to the .up.sql file
        down_file: Path to the .down.sql file

    Note:
        This class is instantiated by the migration loader, not directly by users.
        To create a SQL migration, simply create the .up.sql and .down.sql files.
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        up_file: Path,
        down_file: Path,
    ):
        """Initialize file-based SQL migration.

        Args:
            connection: psycopg3 database connection
            up_file: Path to the .up.sql file
            down_file: Path to the .down.sql file

        Raises:
            FileNotFoundError: If either SQL file doesn't exist
        """
        # Extract version and name from filename before calling super().__init__
        # Filename format: 003_move_catalog_tables.up.sql
        base_name = up_file.name.replace(".up.sql", "")
        parts = base_name.split("_", 1)

        # Set class attributes dynamically for this instance
        # We need to do this before super().__init__ because it validates version/name
        self.__class__ = type(
            f"FileSQLMigration_{base_name}",
            (FileSQLMigration,),
            {
                "version": parts[0] if parts else "???",
                "name": parts[1] if len(parts) > 1 else base_name,
                "up_file": up_file,
                "down_file": down_file,
            },
        )

        self.up_file = up_file
        self.down_file = down_file

        # Validate files exist
        if not up_file.exists():
            raise FileNotFoundError(f"Migration up file not found: {up_file}")
        if not down_file.exists():
            raise FileNotFoundError(f"Migration down file not found: {down_file}")

        super().__init__(connection)

    def up(self) -> None:
        """Apply the migration by executing the .up.sql file."""
        sql = self.up_file.read_text()
        self.execute(sql)

    def down(self) -> None:
        """Rollback the migration by executing the .down.sql file."""
        sql = self.down_file.read_text()
        self.execute(sql)

    @classmethod
    def from_files(
        cls,
        up_file: Path,
        down_file: Path,
    ) -> type["FileSQLMigration"]:
        """Create a migration class from SQL file pair.

        This creates a new class (not instance) that can be used with the
        standard migration system. The class has version and name extracted
        from the filename.

        Args:
            up_file: Path to the .up.sql file
            down_file: Path to the .down.sql file

        Returns:
            A new Migration class (not instance)

        Example:
            >>> MigrationClass = FileSQLMigration.from_files(
            ...     Path("db/migrations/003_move_tables.up.sql"),
            ...     Path("db/migrations/003_move_tables.down.sql"),
            ... )
            >>> migration = MigrationClass(connection=conn)
            >>> migration.up()
        """
        # Extract version and name from filename
        base_name = up_file.name.replace(".up.sql", "")
        parts = base_name.split("_", 1)
        version = parts[0] if parts else "???"
        name = parts[1] if len(parts) > 1 else base_name

        # Create a new class dynamically
        class_name = f"FileSQLMigration_{base_name}"

        def init_method(self: "FileSQLMigration", connection: psycopg.Connection) -> None:
            self.up_file = up_file
            self.down_file = down_file
            self.connection = connection

            # Validate files exist
            if not up_file.exists():
                raise FileNotFoundError(f"Migration up file not found: {up_file}")
            if not down_file.exists():
                raise FileNotFoundError(f"Migration down file not found: {down_file}")

        def up_method(self: "FileSQLMigration") -> None:
            sql = self.up_file.read_text()
            self.execute(sql)

        def down_method(self: "FileSQLMigration") -> None:
            sql = self.down_file.read_text()
            self.execute(sql)

        # Create the class
        new_class = type(
            class_name,
            (Migration,),
            {
                "version": version,
                "name": name,
                "up_file": up_file,
                "down_file": down_file,
                "__init__": init_method,
                "up": up_method,
                "down": down_method,
            },
        )

        return new_class  # type: ignore[return-value]


def find_sql_migration_files(migrations_dir: Path) -> list[tuple[Path, Path]]:
    """Find all SQL migration file pairs in a directory.

    Searches for .up.sql files and matches them with corresponding .down.sql files.

    Args:
        migrations_dir: Directory to search for SQL migrations

    Returns:
        List of (up_file, down_file) tuples, sorted by version

    Raises:
        ValueError: If an .up.sql file has no matching .down.sql file

    Example:
        >>> pairs = find_sql_migration_files(Path("db/migrations"))
        >>> for up_file, down_file in pairs:
        ...     print(f"Found: {up_file.name}")
    """
    pairs: list[tuple[Path, Path]] = []

    # Find all .up.sql files
    for up_file in sorted(migrations_dir.glob("*.up.sql")):
        # Find matching .down.sql
        base_name = up_file.name.replace(".up.sql", "")
        down_file = migrations_dir / f"{base_name}.down.sql"

        if not down_file.exists():
            raise ValueError(
                f"SQL migration {up_file.name} has no matching .down.sql file.\n"
                f"Expected: {down_file}\n"
                f"Hint: Create {down_file.name} with the rollback SQL"
            )

        pairs.append((up_file, down_file))

    return pairs


def get_sql_migration_version(up_file: Path) -> str:
    """Extract version from SQL migration filename.

    Args:
        up_file: Path to the .up.sql file

    Returns:
        Version string (e.g., "003")

    Example:
        >>> get_sql_migration_version(Path("003_move_tables.up.sql"))
        '003'
    """
    base_name = up_file.name.replace(".up.sql", "")
    parts = base_name.split("_", 1)
    return parts[0] if parts else "???"
