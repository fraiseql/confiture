"""Which migration level a live database is at, read against the schema-history snapshots.

Each snapshot is the schema model at one migration — ``<version>_<name>.json``,
``SchemaModel.to_json`` — written beside the migration by ``migrate generate``
(:class:`~confiture.core.schema_snapshot.SchemaSnapshotGenerator`). A history written
before snapshots were model wire holds DDL text (``<version>_<name>.sql``), read through
the one schema read.

The database is compared with each snapshot, newest first, by the one comparison:
``schema_sources.database_side`` reads it in the schemas the snapshot names, with
the snapshot's constants spelled by its server, and ``SchemaDiffer.compare_sides``
compares the two under the policy their sources call for. A database built from the
tree a snapshot was taken of has no change from it, so the first snapshot with none
is the level.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from confiture.core._migrator.discovery import parse_migration_filename
from confiture.core.connection import Connection
from confiture.core.differ import SchemaDiffer, stated_side
from confiture.core.schema_model import SchemaModel
from confiture.core.schema_read import read_text
from confiture.core.schema_sources import database_side
from confiture.exceptions import ConfiturError

logger = logging.getLogger(__name__)

#: A snapshot's file, by what it holds: the model's wire, or (before it) DDL text.
_WIRE, _DDL = ".json", ".sql"


@dataclass(frozen=True)
class Snapshot:
    """The schema at one migration: its version, its name and the model it was."""

    version: str
    name: str
    model: SchemaModel


def _facts(model: SchemaModel) -> int:
    """How many things *model* says: each table, column, constraint and index, and each object."""
    tables = sum(
        1 + len(t.columns) + len(t.constraints) + len(t.indexes) for t in model.tables.values()
    )
    routines = sum(len(found) for found in model.routines.values())
    return (
        tables
        + routines
        + sum(
            len(section)
            for section in (
                model.enum_types,
                model.sequences,
                model.views,
                model.triggers,
                model.tviews,
                model.other_objects,
            )
        )
    )


class BaselineDetector:
    """Detects a database's migration level by comparing it with each snapshot.

    Args:
        snapshots_dir: The schema history (``db/schema_history``).
        similarity_threshold: The share of what the two schemas say that must be
            the same for a snapshot that is not an exact match to be taken as the
            level — for a sparse history, whose database sits between two
            snapshots. ``1.0`` accepts an exact match only.
        tracking_table: The project's ledger, which the database holds and no
            snapshot declares.

    Example:
        >>> with psycopg.connect(db_url) as conn:
        ...     found = BaselineDetector(Path("db/schema_history")).find_matching_snapshot(conn)
        ...     print(found.version if found else "no level")
    """

    def __init__(
        self,
        snapshots_dir: Path,
        similarity_threshold: float = 0.85,
        *,
        tracking_table: str | None = None,
    ) -> None:
        self.snapshots_dir = snapshots_dir
        self.similarity_threshold = similarity_threshold
        self.tracking_table = tracking_table
        #: Each snapshot file that could not be read, and why — reported, never dropped.
        self.unreadable: list[tuple[Path, str]] = []
        self._last_closest: tuple[str, float] | None = None

    def snapshot_files(self) -> list[Path]:
        """Every snapshot file, one per version — the model's wire over DDL text."""
        if not self.snapshots_dir.is_dir():
            return []
        by_version: dict[str, Path] = {}
        for path in sorted(self.snapshots_dir.iterdir()):
            if path.suffix not in (_WIRE, _DDL) or not path.is_file():
                continue
            version = parse_migration_filename(path.stem)[0]
            if version not in by_version or path.suffix == _WIRE:
                by_version[version] = path
        return [by_version[version] for version in sorted(by_version, reverse=True)]

    def load_snapshots(self) -> list[Snapshot]:
        """Every snapshot, newest first; one that cannot be read goes to :attr:`unreadable`."""
        self.unreadable = []
        snapshots = []
        for path in self.snapshot_files():
            version, name = parse_migration_filename(path.stem)
            try:
                snapshots.append(Snapshot(version, name, self._model(path)))
            except (ConfiturError, ValueError, KeyError, TypeError) as exc:
                logger.warning("Schema snapshot %s cannot be read: %s", path, exc)
                self.unreadable.append((path, str(exc)))
        return snapshots

    @staticmethod
    def _model(path: Path) -> SchemaModel:
        text = path.read_text(encoding="utf-8")
        if path.suffix == _WIRE:
            return SchemaModel.from_json(text)
        return read_text(text).catalogued

    def find_matching_snapshot(self, conn: Connection) -> Snapshot | None:
        """The newest snapshot the database at *conn* is, or the closest above the threshold.

        A snapshot the database has no change from is returned at once. Otherwise
        the one with the greatest similarity — the share of what the two say that
        the diff leaves alone — is returned when it reaches
        ``similarity_threshold``, and recorded in :attr:`last_closest` when it
        does not.
        """
        self._last_closest = None
        best: tuple[float, Snapshot] | None = None
        for snapshot in self.load_snapshots():
            similarity = self.similarity(conn, snapshot)
            if similarity == 1.0:
                return snapshot
            if best is None or similarity > best[0]:
                best = (similarity, snapshot)
        if best is None:
            return None
        if best[0] >= self.similarity_threshold:
            return best[1]
        self._last_closest = (best[1].version, best[0])
        return None

    def similarity(self, conn: Connection, snapshot: Snapshot) -> float:
        """The share of what the database and *snapshot* say that is the same: ``1.0`` is no change."""
        live = database_side(conn, against=snapshot.model, tracking_table=self.tracking_table)
        diff = SchemaDiffer().compare_sides(
            stated_side(live.model, live.constants), stated_side(snapshot.model)
        )
        said = max(_facts(live.model), _facts(snapshot.model), 1)
        return max(0.0, 1 - len(diff.changes) / said)

    @property
    def last_closest(self) -> tuple[str, float] | None:
        """``(version, similarity)`` of the closest snapshot after a miss, else ``None``."""
        return self._last_closest
