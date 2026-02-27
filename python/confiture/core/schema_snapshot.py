"""Schema history snapshot writer.

Writes a cumulative DDL snapshot alongside each generated migration file,
enabling auto-detection of migration baselines on databases that have lost
their tracking table (e.g. after a staging restore).
"""

from pathlib import Path

from confiture.core.builder import SchemaBuilder


class SchemaSnapshotGenerator:
    """Writes schema history snapshots to db/schema_history/.

    Each snapshot captures the full cumulative DDL of db/schema/ at the
    moment a migration is generated.  Snapshots are plain SQL files named
    ``<version>_<name>.sql`` and are intended to be committed alongside
    the corresponding migration file.

    Snapshot generation delegates entirely to the existing
    :class:`~confiture.core.builder.SchemaBuilder` so that file-discovery
    and separator logic remains in one place.

    Args:
        snapshots_dir: Directory where snapshot files will be written
            (e.g. ``Path("db/schema_history")``).

    Example:
        >>> gen = SchemaSnapshotGenerator(snapshots_dir=Path("db/schema_history"))
        >>> path = gen.write_snapshot("local", "007", "add_payments", Path("."))
        >>> print(path)
        db/schema_history/007_add_payments.sql
    """

    def __init__(self, snapshots_dir: Path) -> None:
        self.snapshots_dir = snapshots_dir

    def write_snapshot(
        self,
        env: str,
        version: str,
        name: str,
        project_dir: Path | None = None,
    ) -> Path:
        """Build the cumulative schema and write a snapshot file.

        Args:
            env: Environment name used to locate schema directories via
                ``db/environments/{env}.yaml``.
            version: Migration version prefix (e.g. ``"007"``).
            name: Migration name (snake_case, e.g. ``"add_payments"``).
            project_dir: Project root directory.  If ``None``, uses the
                current working directory.

        Returns:
            Path to the written snapshot file.

        Raises:
            SchemaError: If ``SchemaBuilder`` cannot locate or read schema files.
            OSError: If the snapshot file cannot be written.
        """
        builder = SchemaBuilder(env=env, project_dir=project_dir)
        schema_sql = builder.build(schema_only=True)

        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = self.snapshots_dir / f"{version}_{name}.sql"
        snapshot_path.write_text(schema_sql)
        return snapshot_path
