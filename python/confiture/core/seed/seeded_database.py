"""A throwaway database holding a schema and its seeds: built, handed over, dropped.

Building a tree's schema and then its seed files into a scratch database is what
a schema artifact dumps (``schema_artifact.build_schema_artifact``) and what
``confiture seed drift --build`` reads as its seed side. One sequence, so the two
cannot disagree about what a seeded database is: the schema applied through
``psql`` (COPY-aware), each seed file after it, in order, and the database
dropped on every exit.
"""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path

from confiture.core.seed.applier import apply_seed_files
from confiture.core.temp_database import TempDatabase


@contextmanager
def seeded_database(
    server_url: str, schema_sql: str, seed_files: Sequence[Path] = ()
) -> Generator[tuple[str, int]]:
    """``(url, seed files applied)`` of a scratch database on *server_url* holding both.

    Only *server_url*'s server is used: the database is created beside it and
    dropped when the block exits, however it exits.

    Raises:
        SchemaError: the schema or a seed file did not apply (the file is named),
            or ``psql`` is not on PATH.
    """
    temp_db = TempDatabase(server_url)
    with temp_db as temp_url:
        temp_db.apply_schema(temp_url, schema_sql)
        applied = apply_seed_files(temp_url, list(seed_files)) if seed_files else 0
        yield temp_url, applied
