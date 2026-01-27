"""SQL file-based migrations.

Provides support for pure SQL migration files without Python boilerplate.
Migrations are discovered from .up.sql/.down.sql file pairs.

Example file structure:
    db/migrations/
    ├── 001_create_users.py           # Python migration
    ├── 002_add_posts.py              # Python migration
    ├── 003_move_catalog_tables.up.sql    # SQL migration (up)
    ├── 003_move_catalog_tables.down.sql  # SQL migration (down)
    ├── 003_move_catalog_tables.yaml      # Optional: preconditions

The migrator will automatically detect and load SQL file pairs alongside
Python migrations.

Preconditions for SQL-only migrations can be defined in a YAML sidecar file:

    # 003_move_catalog_tables.yaml
    up_preconditions:
      - type: TableExists
        table: tb_datasupplier
        schema: tenant
      - type: TableNotExists
        table: tb_datasupplier
        schema: catalog

    down_preconditions:
      - type: TableExists
        table: tb_datasupplier
        schema: catalog
"""

from pathlib import Path

import psycopg

from confiture.core.preconditions import Precondition
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

        If a YAML sidecar file exists (e.g., 003_move_tables.yaml), preconditions
        will be loaded from it and applied to the migration class.

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

        # Load preconditions from YAML sidecar if it exists
        up_preconditions: list[Precondition] = []
        down_preconditions: list[Precondition] = []

        yaml_sidecar = find_yaml_sidecar(up_file)
        if yaml_sidecar:
            up_preconditions, down_preconditions = load_preconditions_from_yaml(yaml_sidecar)

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
                "up_preconditions": up_preconditions,
                "down_preconditions": down_preconditions,
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


def load_preconditions_from_yaml(
    yaml_file: Path,
) -> tuple[list["Precondition"], list["Precondition"]]:
    """Load preconditions from a YAML sidecar file.

    The YAML file should have the following structure:

        up_preconditions:
          - type: TableExists
            table: users
            schema: public
          - type: ColumnNotExists
            table: users
            column: legacy_field

        down_preconditions:
          - type: TableExists
            table: users_backup

    Supported precondition types:
        - TableExists, TableNotExists
        - ColumnExists, ColumnNotExists, ColumnType
        - ConstraintExists, ConstraintNotExists
        - ForeignKeyExists
        - IndexExists, IndexNotExists
        - SchemaExists, SchemaNotExists
        - RowCountEquals, RowCountGreaterThan, TableIsEmpty
        - CustomSQL

    Args:
        yaml_file: Path to the YAML file

    Returns:
        Tuple of (up_preconditions, down_preconditions)

    Raises:
        ValueError: If precondition type is unknown or required fields are missing
        FileNotFoundError: If YAML file doesn't exist
    """
    import yaml

    from confiture.core.preconditions import (
        ColumnExists,
        ColumnNotExists,
        ColumnType,
        ConstraintExists,
        ConstraintNotExists,
        CustomSQL,
        ForeignKeyExists,
        IndexExists,
        IndexNotExists,
        RowCountEquals,
        RowCountGreaterThan,
        SchemaExists,
        SchemaNotExists,
        TableExists,
        TableIsEmpty,
        TableNotExists,
    )

    # Mapping of type names to classes
    PRECONDITION_TYPES: dict[str, type] = {
        "TableExists": TableExists,
        "TableNotExists": TableNotExists,
        "ColumnExists": ColumnExists,
        "ColumnNotExists": ColumnNotExists,
        "ColumnType": ColumnType,
        "ConstraintExists": ConstraintExists,
        "ConstraintNotExists": ConstraintNotExists,
        "ForeignKeyExists": ForeignKeyExists,
        "IndexExists": IndexExists,
        "IndexNotExists": IndexNotExists,
        "SchemaExists": SchemaExists,
        "SchemaNotExists": SchemaNotExists,
        "RowCountEquals": RowCountEquals,
        "RowCountGreaterThan": RowCountGreaterThan,
        "TableIsEmpty": TableIsEmpty,
        "CustomSQL": CustomSQL,
    }

    if not yaml_file.exists():
        raise FileNotFoundError(f"YAML file not found: {yaml_file}")

    with yaml_file.open() as f:
        data = yaml.safe_load(f) or {}

    def parse_preconditions(items: list[dict] | None) -> list["Precondition"]:
        if not items:
            return []

        preconditions: list[Precondition] = []
        for item in items:
            precondition_type = item.pop("type", None)
            if not precondition_type:
                raise ValueError(f"Precondition missing 'type' field: {item}")

            if precondition_type not in PRECONDITION_TYPES:
                raise ValueError(
                    f"Unknown precondition type: {precondition_type}. "
                    f"Available types: {', '.join(PRECONDITION_TYPES.keys())}"
                )

            precondition_class = PRECONDITION_TYPES[precondition_type]
            try:
                preconditions.append(precondition_class(**item))
            except TypeError as e:
                raise ValueError(f"Invalid arguments for {precondition_type}: {e}") from e

        return preconditions

    up_preconditions = parse_preconditions(data.get("up_preconditions"))
    down_preconditions = parse_preconditions(data.get("down_preconditions"))

    return (up_preconditions, down_preconditions)


def find_yaml_sidecar(up_file: Path) -> Path | None:
    """Find the YAML sidecar file for a SQL migration.

    Args:
        up_file: Path to the .up.sql file

    Returns:
        Path to the .yaml file if it exists, None otherwise

    Example:
        >>> find_yaml_sidecar(Path("003_move_tables.up.sql"))
        Path("003_move_tables.yaml")  # or None if not found
    """
    base_name = up_file.name.replace(".up.sql", "")
    yaml_file = up_file.parent / f"{base_name}.yaml"

    if yaml_file.exists():
        return yaml_file
    return None
