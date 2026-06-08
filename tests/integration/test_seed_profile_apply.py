"""Integration: a slim seed profile applies only its subset (P4, Cycle 4).

Requires a reachable local PostgreSQL.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from confiture.config.environment import SeedProfile
from confiture.core.seed_applier import SeedApplier
from confiture.core.temp_database import TempDatabase, _maintenance_url

pytestmark = pytest.mark.integration


def _server_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


@pytest.fixture
def temp_db_url() -> Iterator[str]:
    url = _server_url()
    try:
        with psycopg.connect(_maintenance_url(url), autocommit=True):
            pass
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")
    with TempDatabase(url) as temp_url:
        with psycopg.connect(temp_url, autocommit=True) as conn:
            conn.execute("CREATE TABLE loaded (name text)")
        yield temp_url


def _seeds(tmp_path: Path) -> Path:
    d = tmp_path / "seeds"
    d.mkdir()
    (d / "core_1.sql").write_text("INSERT INTO loaded (name) VALUES ('core');")
    (d / "stats_1.sql").write_text("INSERT INTO loaded (name) VALUES ('stats');")
    return d


def test_slim_profile_loads_only_subset(temp_db_url: str, tmp_path: Path) -> None:
    seeds_dir = _seeds(tmp_path)
    with psycopg.connect(temp_db_url, autocommit=False) as conn:
        applier = SeedApplier(seeds_dir=seeds_dir, connection=conn)
        result = applier.apply_sequential(profile=SeedProfile(exclude=["stats_*.sql"]))
        conn.commit()

    assert result.succeeded == 1
    with psycopg.connect(temp_db_url, autocommit=True) as conn:
        rows = {r[0] for r in conn.execute("SELECT name FROM loaded").fetchall()}
    assert rows == {"core"}


def test_no_profile_loads_all(temp_db_url: str, tmp_path: Path) -> None:
    seeds_dir = _seeds(tmp_path)
    with psycopg.connect(temp_db_url, autocommit=False) as conn:
        applier = SeedApplier(seeds_dir=seeds_dir, connection=conn)
        applier.apply_sequential()
        conn.commit()

    with psycopg.connect(temp_db_url, autocommit=True) as conn:
        rows = {r[0] for r in conn.execute("SELECT name FROM loaded").fetchall()}
    assert rows == {"core", "stats"}
