"""Cacheable schema-artifact dumper (Medium 1, CI provisioning).

Produces a content-addressed ``pg_dump -Fc`` (custom) or ``-Fd`` (directory)
archive of a fully-built schema so that CI can cache schema provisioning by the
``db/`` content hash instead of treating schema-apply as an uncacheable live-DB
side effect, and restore it in parallel via the three-phase
:class:`confiture.core.restorer.DatabaseRestorer`.

The archive is produced by building the freshly-generated schema (plus optional
seed files) into an **ephemeral throwaway database** and dumping *that*, so the
artifact's content always matches the ``db/`` source whose hash names it — never
a drifted live database.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import psycopg

from confiture.core.seed_executor import SeedExecutor
from confiture.core.temp_database import TempDatabase
from confiture.exceptions import SchemaError

# Supported pg_dump archive formats → the format flag and on-disk extension.
_DUMP_FORMAT_FLAG = {"custom": "-Fc", "directory": "-Fd"}
_DUMP_FORMAT_EXT = {"custom": "pgdump", "directory": "pgdir"}


@dataclass
class ArtifactResult:
    """Outcome of an artifact build.

    Attributes:
        artifact_path: Path to the produced (or reused) archive.
        artifact_hash: The ``db/`` content hash the artifact corresponds to.
        dump_format: ``"custom"`` or ``"directory"``.
        skipped: True if an up-to-date artifact already existed and the dump was
            a no-op.
        seed_files_applied: Number of seed files loaded into the ephemeral DB
            before dumping.
    """

    artifact_path: Path
    artifact_hash: str
    dump_format: str
    skipped: bool = False
    seed_files_applied: int = 0


def default_artifact_path(
    output_dir: Path,
    env: str,
    schema_hash: str,
    *,
    profile: str | None = None,
    dump_format: str = "custom",
) -> Path:
    """Build the content-addressed default artifact path.

    The filename embeds the environment, the seed-profile name, and the first 12
    characters of the schema content hash, so that an unchanged ``db/`` resolves
    to the same path (cache hit) while a different schema *or* seed profile
    resolves to a distinct one (no slim/full collision).

    Args:
        output_dir: Directory to place the artifact in.
        env: Environment name.
        schema_hash: Full schema content hash (``builder.compute_hash()``).
        profile: Seed-profile name, or None for the full seed set.
        dump_format: ``"custom"`` or ``"directory"``.

    Returns:
        The resolved artifact path.
    """
    profile_seg = profile or "full"
    ext = _DUMP_FORMAT_EXT.get(dump_format, _DUMP_FORMAT_EXT["custom"])
    return Path(output_dir) / f"schema_{env}.{profile_seg}.{schema_hash[:12]}.{ext}"


class SchemaArtifactDumper:
    """Thin wrapper around ``pg_dump`` for custom/directory-format archives.

    Args:
        jobs: Parallel workers for directory-format dumps (ignored for custom
            format, which pg_dump cannot parallelise).
    """

    def __init__(self, *, jobs: int = 4) -> None:
        self.jobs = jobs

    def build_argv(
        self, source_url: str, output_path: Path, dump_format: str = "custom"
    ) -> list[str]:
        """Construct the ``pg_dump`` argument list.

        Args:
            source_url: Connection URL of the database to dump.
            output_path: Destination archive path.
            dump_format: ``"custom"`` (-Fc) or ``"directory"`` (-Fd).

        Returns:
            Full argv list.

        Raises:
            SchemaError: If ``dump_format`` is not supported.
        """
        try:
            fmt_flag = _DUMP_FORMAT_FLAG[dump_format]
        except KeyError as e:
            raise SchemaError(
                f"Unsupported dump format: {dump_format!r}.",
                resolution_hint="Use --dump-format custom or directory.",
            ) from e

        argv = ["pg_dump", fmt_flag]
        if dump_format == "directory" and self.jobs > 1:
            argv += ["-j", str(self.jobs)]
        argv += ["-d", str(source_url), "-f", str(output_path)]
        return argv

    def dump(
        self, source_url: str, output_path: Path, dump_format: str = "custom"
    ) -> None:
        """Run ``pg_dump`` to produce the archive.

        Args:
            source_url: Connection URL of the database to dump.
            output_path: Destination archive path.
            dump_format: ``"custom"`` or ``"directory"``.

        Raises:
            SchemaError: If ``pg_dump`` is missing or exits non-zero.
        """
        argv = self.build_argv(source_url, output_path, dump_format)
        try:
            result = subprocess.run(argv, capture_output=True, text=True, check=False)
        except FileNotFoundError as e:
            raise SchemaError(
                "pg_dump not found on PATH. Install postgresql-client.",
                resolution_hint="Ensure PostgreSQL client tools are installed and on PATH.",
            ) from e

        if result.returncode != 0:
            stderr_tail = "\n".join((result.stderr or "").strip().splitlines()[-5:])
            raise SchemaError(
                f"pg_dump failed: {stderr_tail}",
                resolution_hint="Check the connection URL and that the schema applied cleanly.",
            )


def _apply_seed_files(temp_url: str, seed_files: list[Path]) -> int:
    """Apply seed files into the ephemeral database, each in its own savepoint.

    Args:
        temp_url: Connection URL of the ephemeral database.
        seed_files: Ordered seed files to apply.

    Returns:
        The number of seed files applied.
    """
    with psycopg.connect(temp_url, autocommit=False) as conn:
        executor = SeedExecutor(connection=conn)
        for i, seed_file in enumerate(seed_files, 1):
            executor.execute_file(seed_file, savepoint_name=f"sp_artifact_seed_{i:03d}")
        conn.commit()
    return len(seed_files)


def build_schema_artifact(
    *,
    server_url: str,
    schema_sql: str,
    output_path: Path,
    schema_hash: str,
    seed_files: list[Path] | None = None,
    dump_format: str = "custom",
    dumper: SchemaArtifactDumper | None = None,
) -> ArtifactResult:
    """Build a content-addressed schema artifact via an ephemeral database.

    If ``output_path`` already exists it is treated as an up-to-date cache hit
    (the path is content-addressed by ``schema_hash``) and the dump is skipped.
    Otherwise the schema (and any seed files) are applied into a throwaway
    :class:`TempDatabase`, dumped, and the throwaway database is dropped.

    Args:
        server_url: PostgreSQL server URL; only its server component is used (the
            database is ignored — an ephemeral DB is created on that server).
        schema_sql: Fully-built schema DDL to apply.
        output_path: Destination artifact path (content-addressed by the caller).
        schema_hash: The ``db/`` content hash this artifact corresponds to.
        seed_files: Optional ordered seed files to load before dumping.
        dump_format: ``"custom"`` or ``"directory"``.
        dumper: Injectable dumper (for testing); a default is created otherwise.

    Returns:
        :class:`ArtifactResult` describing the produced or reused artifact.

    Raises:
        SchemaError: If schema/seed application or the dump fails.
    """
    output_path = Path(output_path)
    if output_path.exists():
        return ArtifactResult(
            artifact_path=output_path,
            artifact_hash=schema_hash,
            dump_format=dump_format,
            skipped=True,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dumper = dumper or SchemaArtifactDumper()
    seeds_applied = 0

    temp_db = TempDatabase(server_url)
    with temp_db as temp_url:
        temp_db.apply_schema(temp_url, schema_sql)
        if seed_files:
            seeds_applied = _apply_seed_files(temp_url, seed_files)
        dumper.dump(temp_url, output_path, dump_format)

    return ArtifactResult(
        artifact_path=output_path,
        artifact_hash=schema_hash,
        dump_format=dump_format,
        skipped=False,
        seed_files_applied=seeds_applied,
    )
