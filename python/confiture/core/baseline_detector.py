"""Baseline detector for auto-detecting migration level from a live database.

Compares a normalised representation of the live database schema against
stored schema history snapshots to identify the migration version that
matches the current state of the database.

**v1 scope:** Tables and columns only.  Views, functions, triggers, and
sequences are out of scope and are ignored during live introspection.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

import psycopg

from confiture.core.introspector import SchemaIntrospector
from confiture.models.introspection import IntrospectionResult


class BaselineDetector:
    """Detects migration baseline by comparing live DB schema to snapshots.

    Uses the existing :class:`~confiture.core.introspector.SchemaIntrospector`
    (which queries ``pg_catalog``, not ``information_schema``) to reconstruct
    the live schema as SQL, then normalises and compares it against the
    snapshot files in ``snapshots_dir``.

    Matching uses fuzzy/structural comparison: first tries exact match, then
    returns the best match if its similarity exceeds the threshold (default 0.95).
    This allows baseline detection to work with sparse snapshot sets where the
    live database is at an intermediate migration state.

    Args:
        snapshots_dir: Directory containing ``<version>_<name>.sql`` snapshot
            files written by :class:`~confiture.core.schema_snapshot.SchemaSnapshotGenerator`.
        similarity_threshold: Minimum similarity ratio (0.0-1.0) to accept a match
            when no exact match is found (default: 0.85). Works well for sparse
            snapshots where the live database is at an intermediate migration state.
            Set lower (e.g., 0.75) for looser matching, higher (e.g., 0.95) for stricter.

    Example:
        >>> with psycopg.connect(db_url) as conn:
        ...     detector = BaselineDetector(Path("db/schema_history"))
        ...     live_sql = detector.introspect_live_schema(conn)
        ...     version = detector.find_matching_snapshot(live_sql)
        ...     print(version)  # e.g. "007"

    Example with custom threshold:
        >>> detector = BaselineDetector(
        ...     Path("db/schema_history"),
        ...     similarity_threshold=0.98  # stricter matching
        ... )
    """

    def __init__(self, snapshots_dir: Path, similarity_threshold: float = 0.85) -> None:
        self.snapshots_dir = snapshots_dir
        self.similarity_threshold = similarity_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def normalize_schema(self, sql: str) -> str:
        """Normalise SQL for structural comparison.

        Applies the following transformations so that cosmetic differences
        (whitespace, comments, ``IF NOT EXISTS``) do not prevent a match:

        - Strip SQL line comments (``-- ...``) and block comments (``/* ... */``)
        - Lowercase all text
        - Collapse all whitespace runs to a single space
        - Remove ``if not exists`` and ``if exists`` clauses
        - Sort ``CREATE TABLE`` blocks alphabetically by table name

        Args:
            sql: Raw SQL string to normalise.

        Returns:
            Normalised SQL string suitable for equality comparison.
        """
        # Remove block comments
        sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
        # Remove line comments
        sql = re.sub(r"--[^\n]*", " ", sql)
        # Lowercase
        sql = sql.lower()
        # Remove IF NOT EXISTS / IF EXISTS
        sql = re.sub(r"\bif\s+not\s+exists\b", "", sql)
        sql = re.sub(r"\bif\s+exists\b", "", sql)
        # Collapse whitespace
        sql = re.sub(r"\s+", " ", sql).strip()
        # Sort CREATE TABLE blocks for deterministic order
        sql = self._sort_create_table_blocks(sql)
        return sql

    def load_snapshots(self) -> list[tuple[str, str]]:
        """Load and normalise all snapshot files, newest version first.

        Returns:
            List of ``(version, normalised_sql)`` tuples sorted by version
            descending (newest first) for efficient matching.
        """
        if not self.snapshots_dir.exists():
            return []

        snapshots = []
        for path in sorted(self.snapshots_dir.glob("*.sql"), reverse=True):
            version = path.name.split("_")[0]
            normalised = self.normalize_schema(path.read_text())
            snapshots.append((version, normalised))
        return snapshots

    def find_matching_snapshot(self, live_schema_sql: str) -> str | None:
        """Find the snapshot version that matches the live schema.

        Uses fuzzy matching with a configurable similarity threshold. First checks
        for exact matches (100% similarity), then returns the best match if its
        similarity exceeds the threshold (default 0.95).

        This allows auto-detection to work with sparse snapshot sets where the live
        database sits between two snapshots (e.g., after migration consolidation).

        Args:
            live_schema_sql: Raw SQL reconstructed from the live database
                (e.g. from :meth:`introspect_live_schema`).

        Returns:
            Matching version string (e.g. ``"007"``) if best match exceeds the
            similarity threshold, or ``None`` if no match found. The closest
            non-matching snapshot is stored in :attr:`last_closest` for diagnostics.
        """
        normalised_live = self.normalize_schema(live_schema_sql)
        snapshots = self.load_snapshots()

        if not snapshots:
            return None

        best_ratio = 0.0
        best_version = ""
        for version, normalised_snapshot in snapshots:
            # Exact match: return immediately
            if normalised_live == normalised_snapshot:
                return version
            # Fuzzy match: track best similarity
            ratio = difflib.SequenceMatcher(None, normalised_live, normalised_snapshot).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_version = version

        # Return best match if it exceeds the similarity threshold
        if best_ratio >= self.similarity_threshold:
            return best_version

        # No match above threshold — store diagnostic info
        self._last_closest = (best_version, best_ratio)
        return None

    def introspect_live_schema(self, conn: psycopg.Connection) -> str:
        """Reconstruct the live database schema as SQL using pg_catalog.

        Delegates to the existing
        :class:`~confiture.core.introspector.SchemaIntrospector` (which uses
        ``pg_catalog``, not ``information_schema``) to guarantee accurate
        PostgreSQL type names.

        **v1 scope:** Tables and columns only.

        Args:
            conn: Open ``psycopg`` connection to the target database.

        Returns:
            SQL string with one ``CREATE TABLE`` block per table, suitable
            for passing to :meth:`normalize_schema`.
        """
        result: IntrospectionResult = SchemaIntrospector(conn).introspect(
            all_tables=True, include_hints=False
        )
        return self._introspection_result_to_sql(result)

    # ------------------------------------------------------------------
    # Closest-match diagnostics
    # ------------------------------------------------------------------

    @property
    def last_closest(self) -> tuple[str, float] | None:
        """Return ``(version, similarity_ratio)`` of the closest non-matching snapshot.

        Only populated after a failed :meth:`find_matching_snapshot` call.
        Returns ``None`` if not yet set.
        """
        return getattr(self, "_last_closest", None)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _sort_create_table_blocks(self, sql: str) -> str:
        """Re-order ``CREATE TABLE`` blocks alphabetically by table name.

        Splits on ``create table`` boundaries, sorts each block, and
        reassembles.  Non-table SQL before the first ``create table`` is
        preserved as a prefix.

        Args:
            sql: Already lowercased, whitespace-collapsed SQL.

        Returns:
            SQL with ``CREATE TABLE`` blocks in alphabetical order.
        """
        parts = re.split(r"(?=create\s+table\s)", sql)
        if len(parts) <= 1:
            return sql

        prefix = parts[0]
        table_blocks = parts[1:]

        def _table_name(block: str) -> str:
            m = re.match(r"create\s+table\s+(\S+)", block)
            return m.group(1) if m else block

        table_blocks.sort(key=_table_name)
        return prefix + "".join(table_blocks)

    def _introspection_result_to_sql(self, result: IntrospectionResult) -> str:
        """Convert an IntrospectionResult to a CREATE TABLE SQL string.

        Args:
            result: :class:`~confiture.models.introspection.IntrospectionResult`
                returned by :class:`~confiture.core.introspector.SchemaIntrospector`.

        Returns:
            SQL string with one ``CREATE TABLE`` block per table.
        """
        blocks = []
        for table in result.tables:
            col_defs = []
            pk_cols = [c.name for c in table.columns if c.is_primary_key]
            for col in table.columns:
                null_clause = "" if col.nullable else " not null"
                col_defs.append(f"  {col.name} {col.pg_type}{null_clause}")
            if pk_cols:
                col_defs.append(f"  primary key ({', '.join(pk_cols)})")
            cols_sql = ",\n".join(col_defs)
            blocks.append(f"create table {table.name} (\n{cols_sql}\n);")
        return "\n\n".join(blocks)
