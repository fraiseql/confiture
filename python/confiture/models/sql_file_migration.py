"""SQL file-based migrations.

Provides support for pure SQL migration files without Python boilerplate.
Migrations are discovered from .up.sql/.down.sql file pairs.

Example file structure:
    db/migrations/
    ├── 20260228120530_create_users.py           # Python migration
    ├── 20260228120531_add_posts.py              # Python migration
    ├── 20260228120532_move_catalog_tables.up.sql    # SQL migration (up)
    ├── 20260228120532_move_catalog_tables.down.sql  # SQL migration (down)
    ├── 20260228120532_move_catalog_tables.yaml      # Optional: preconditions

The migrator will automatically detect and load SQL file pairs alongside
Python migrations.

Preconditions for SQL-only migrations can be defined in a YAML sidecar file:

    # 20260228120532_move_catalog_tables.yaml
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

import logging
from pathlib import Path

import pglast.parser
import psycopg

from confiture.core._migrator.discovery import parse_migration_filename
from confiture.core.preconditions import Precondition
from confiture.core.sql_lexer import split_statements
from confiture.core.sql_utils import strip_transaction_wrappers
from confiture.models.migration import Migration

logger = logging.getLogger(__name__)


def _down_for(up_file: Path) -> Path:
    """The ``.down.sql`` twin of an ``.up.sql`` path."""
    return up_file.with_name(up_file.name[: -len(".up.sql")] + ".down.sql")


def _detect_transactional(up_file: Path) -> bool:
    """Return ``False`` when a SQL migration must run outside a transaction.

    A pure ``.up.sql`` migration has no Python class to carry
    ``transactional = False``, yet statements such as ``CREATE INDEX
    CONCURRENTLY``, ``VACUUM``, ``REINDEX … CONCURRENTLY`` and ``ALTER TYPE …
    ADD VALUE`` are rejected by PostgreSQL inside any transaction block.  This
    mirrors the static ``preflight`` check (``MigrationAnalyzer`` on the up
    file) so such a migration runs in autocommit under ``migrate up`` and is
    skipped under ``preflight --against`` — exactly like a Python migration
    that declares ``transactional = False`` (issue #169).

    Any read or analysis failure degrades to ``True`` (transactional), the
    historical default; the real error surfaces when the migration executes.
    """
    from confiture.core.migration_analyzer import MigrationAnalyzer

    try:
        sql = up_file.read_text(encoding="utf-8")
        try:
            return not MigrationAnalyzer().analyze(sql)
        except pglast.parser.ParseError:
            # The statement is about to be executed: PostgreSQL will reject it
            # with its own error inside the transaction. Nothing to classify.
            return True
    except (OSError, UnicodeDecodeError):
        return True


def _execute_sql_script(migration: Migration, sql: str) -> None:
    """Run a migration file's SQL through ``migration.execute``.

    A transactional migration goes to the server as one script inside
    confiture's transaction. A non-transactional one (``CREATE INDEX
    CONCURRENTLY``, ``VACUUM``, …) runs under autocommit — but PostgreSQL
    still wraps a multi-statement string in an implicit transaction block, so
    it is split with the shared splitter and sent one statement at a time.
    """
    if getattr(migration, "transactional", True):
        migration.execute(sql)
        return
    for statement in split_statements(sql):
        migration.execute(statement)


class FileSQLMigration(Migration):
    """Migration loaded from .up.sql/.down.sql file pair.

    This class is instantiated dynamically by the migrator when it discovers
    SQL file pairs. Users don't create these directly - they just create the
    SQL files.

    The version and name are extracted from the filename:
    - `20260228120532_move_catalog_tables.up.sql` → version="20260228120532", name="move_catalog_tables"

    Attributes:
        up_file: Path to the .up.sql file
        down_file: Path to the .down.sql file

    Note:
        This class is instantiated by the migration loader, not directly by users.
        To create a SQL migration, simply create the .up.sql and .down.sql files.
    """

    # ``from_files`` subclasses set these at class level. The base class is only
    # instantiated directly with explicit paths, which fill them per instance;
    # the placeholders satisfy ``Migration.__init__``'s class-attribute check.
    version: str = ""
    name: str = ""
    up_file: Path
    down_file: Path

    def __init__(
        self,
        connection: psycopg.Connection,
        up_file: Path | None = None,
        down_file: Path | None = None,
    ):
        """Bind a connection; a subclass from :meth:`from_files` carries the files.

        Constructing ``FileSQLMigration`` directly with the two paths sets
        version, name and the transactional flag on the instance from the
        ``.up.sql`` file.

        Raises:
            FileNotFoundError: If either file does not exist.
        """
        if up_file is not None:
            self.up_file = up_file
            self.down_file = down_file if down_file is not None else _down_for(up_file)
            self.version, self.name = parse_migration_filename(up_file.name)
            self.transactional = _detect_transactional(up_file)
        if not self.up_file.exists():
            raise FileNotFoundError(f"Migration up file not found: {self.up_file}")
        if not self.down_file.exists():
            raise FileNotFoundError(f"Migration down file not found: {self.down_file}")
        super().__init__(connection)

    def get_up_sql_statements(self) -> list[str]:
        """Get individual SQL statements from the .up.sql file.

        Returns:
            List of SQL statements parsed from the file
        """
        sql, _ = strip_transaction_wrappers(self.up_file.read_text(), return_changed=True)
        return split_statements(sql)

    def up(self) -> None:
        """Apply the migration by executing the .up.sql file."""
        sql, changed = strip_transaction_wrappers(self.up_file.read_text(), return_changed=True)
        if changed:
            logger.warning(
                "Migration %s (%s): stripped BEGIN/COMMIT from .up.sql — "
                "confiture manages transactions; omit them from migration files.",
                self.version,
                self.up_file.name,
            )
        self._execute_script(sql)

    def down(self) -> None:
        """Rollback the migration by executing the .down.sql file."""
        sql, changed = strip_transaction_wrappers(self.down_file.read_text(), return_changed=True)
        if changed:
            logger.warning(
                "Migration %s (%s): stripped BEGIN/COMMIT from .down.sql — "
                "confiture manages transactions; omit them from migration files.",
                self.version,
                self.down_file.name,
            )
        self._execute_script(sql)

    def _execute_script(self, sql: str) -> None:
        """Run the file's SQL — see :func:`_execute_sql_script`."""
        _execute_sql_script(self, sql)

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
        version, name = parse_migration_filename(up_file.name)

        up_preconditions: list[Precondition] = []
        down_preconditions: list[Precondition] = []
        yaml_sidecar = find_yaml_sidecar(up_file)
        if yaml_sidecar:
            up_preconditions, down_preconditions = load_preconditions_from_yaml(yaml_sidecar)

        return type(
            f"FileSQLMigration_{version}_{name}",
            (FileSQLMigration,),
            {
                "version": version,
                "name": name,
                "up_file": up_file,
                "down_file": down_file,
                "up_preconditions": up_preconditions,
                "down_preconditions": down_preconditions,
                # Issue #169 — a SQL file containing CREATE INDEX CONCURRENTLY,
                # VACUUM, etc. cannot run inside a transaction; detect that here
                # (same analyzer as the static preflight check) so `migrate up`
                # applies it in autocommit and `preflight --against` skips it.
                "transactional": _detect_transactional(up_file),
            },
        )


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
    return parse_migration_filename(up_file.name)[0]


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
