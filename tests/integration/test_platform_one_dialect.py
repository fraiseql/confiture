"""``database`` is a URL or a connection wherever the seam runs on one (#374).

``validate_seeds`` took only ``database_url=``; a caller holding a connection had
to hand over a URL and let the validator open a second session. It now takes
either, and on a caller's connection it leaves the caller's transaction as it
found it. A call never changes a caller's connection's mode: one that needs a
transaction refuses a connection in autocommit.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from confiture import platform

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "08-generated-seeds" / "db"
SCHEMA = EXAMPLE / "schema"
SEEDS = EXAMPLE / "seeds" / "prep"


@pytest.fixture
def prep_seed_database(fresh_database: str) -> str:
    """The generated-seeds example's schema, built; no rows anywhere."""
    with psycopg.connect(fresh_database) as conn:
        for sql in sorted(SCHEMA.rglob("*.sql")):
            conn.execute(sql.read_text())
    return fresh_database


def _messages(report: platform.PrepSeedReport) -> list[str]:
    return sorted(v.message for v in report.violations)


def test_a_connection_validates_as_the_url_does(prep_seed_database: str) -> None:
    by_url = platform.validate_seeds(
        SEEDS, schema_dir=SCHEMA, max_level=5, database=prep_seed_database
    )
    with psycopg.connect(prep_seed_database) as conn:
        by_connection = platform.validate_seeds(
            SEEDS, schema_dir=SCHEMA, max_level=5, database=conn
        )
    assert _messages(by_connection) == _messages(by_url) == []


def test_the_callers_transaction_is_left_as_it_was(prep_seed_database: str) -> None:
    """What the caller did before the call stands; what the validator loaded does not."""
    with psycopg.connect(prep_seed_database) as conn:
        conn.execute("CREATE TABLE public.marker (x INT)")
        conn.execute("INSERT INTO public.marker VALUES (1)")
        platform.validate_seeds(SEEDS, schema_dir=SCHEMA, max_level=5, database=conn)
        assert not conn.closed
        assert conn.execute("SELECT count(*) FROM public.marker").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM catalog.tb_product").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM prep_seed.tb_product").fetchone() == (0,)
        conn.rollback()


def test_a_connection_in_autocommit_is_refused_not_switched(prep_seed_database: str) -> None:
    with psycopg.connect(prep_seed_database, autocommit=True) as conn:
        with pytest.raises(platform.ConfigurationError, match="validate_seeds") as caught:
            platform.validate_seeds(SEEDS, schema_dir=SCHEMA, max_level=4, database=conn)
        assert caught.value.error_code == "CONFIG_013"
        assert conn.autocommit is True


def test_the_static_levels_take_any_connection(prep_seed_database: str) -> None:
    """Levels 1-3 never reach the database, so its mode is not theirs to refuse."""
    with psycopg.connect(prep_seed_database, autocommit=True) as conn:
        report = platform.validate_seeds(SEEDS, schema_dir=SCHEMA, max_level=3, database=conn)
    assert report.violations == []
