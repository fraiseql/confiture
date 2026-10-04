"""Schema history snapshot writer.

Writes the schema model a migration leaves (``SchemaModel.to_json``) beside each
generated migration, so the migration level of a database that lost its ledger can
be recovered (:class:`~confiture.core.baseline_detector.BaselineDetector`).
"""

from pathlib import Path

from confiture.core.builder import SchemaBuilder
from confiture.core.schema_sources import materialised_side, read_schema


class SchemaSnapshotGenerator:
    """Writes schema history snapshots to ``db/schema_history/``.

    Each snapshot is ``<version>_<name>.json``: the model of the cumulative schema at
    the moment the migration is generated, sorted and byte-stable, meant to be
    committed with the migration. The schema is the environment's build, read by
    the one schema read, as PostgreSQL holds it once applied.

    With a ``database_url`` (**live mode**), the build is applied to a throwaway
    database on that server and read back from its catalog instead: what PostgreSQL
    built, objects a ``DO`` block created included.

    Args:
        snapshots_dir: Directory where snapshot files are written
            (e.g. ``Path("db/schema_history")``).

    Example:
        >>> gen = SchemaSnapshotGenerator(snapshots_dir=Path("db/schema_history"))
        >>> path = gen.write_snapshot("local", "007", "add_payments", Path("."))
        >>> print(path)
        db/schema_history/007_add_payments.json
    """

    def __init__(self, snapshots_dir: Path) -> None:
        self.snapshots_dir = snapshots_dir

    def write_snapshot(
        self,
        env: str,
        version: str,
        name: str,
        project_dir: Path | None = None,
        *,
        database_url: str | None = None,
    ) -> Path:
        """Read the cumulative schema and write its model as a snapshot file.

        Args:
            env: Environment whose build the snapshot is (``db/environments/{env}.yaml``).
            version: Migration version prefix (e.g. ``"007"``).
            name: Migration name (snake_case, e.g. ``"add_payments"``).
            project_dir: Project root directory; the current directory when ``None``.
            database_url: A writable server: when given, the build is applied to a
                throwaway database there and the snapshot is its catalog's model.

        Returns:
            Path to the written snapshot file.

        Raises:
            SchemaError: If the schema files cannot be read or parsed, or the
                server cannot build them.
            OSError: If the snapshot file cannot be written.
        """
        read = read_schema(env=env, project_dir=project_dir)
        model = read.catalogued
        if database_url is not None:
            sql = SchemaBuilder(env=env, project_dir=project_dir).build(schema_only=True)
            model = materialised_side(sql, database_url, declared=read.model).model

        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = self.snapshots_dir / f"{version}_{name}.json"
        snapshot_path.write_text(model.to_json() + "\n", encoding="utf-8")
        return snapshot_path
