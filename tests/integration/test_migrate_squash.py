"""``migrate squash``, then ``migrate up`` on each kind of database (#539).

After a squash the migrations directory holds the baseline and what came after
it; the squashed files are in ``archive/``. ``migrate up`` then meets a pending
baseline, and what it does depends on the ledger:

- empty (a fresh database): it applies the baseline like any migration;
- holding every squashed version, with the checksums the baseline's digest was
  made from: it records the baseline without running it and marks those rows
  ``archived_into``, in one transaction;
- anything else: it refuses (``VALID_008``) before changing anything.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture.core.migrator import MigratorSession
from confiture.core.squash import execute_squash, plan_squash
from confiture.exceptions import ValidationError

pytestmark = pytest.mark.integration

MIGRATIONS = {
    "20260101000000_users": ("CREATE TABLE users (id int PRIMARY KEY);\n", "DROP TABLE users;\n"),
    "20260102000000_email": (
        "ALTER TABLE users ADD COLUMN email text;\n",
        "ALTER TABLE users DROP COLUMN email;\n",
    ),
    "20260103000000_posts": (
        "CREATE TABLE posts (id int PRIMARY KEY, author int REFERENCES users);\n",
        "DROP TABLE posts;\n",
    ),
}
THROUGH = "20260102000000"
BASELINE = "20260102000001"


@pytest.fixture
def migrations(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    for stem, (up, down) in MIGRATIONS.items():
        (directory / f"{stem}.up.sql").write_text(up)
        (directory / f"{stem}.down.sql").write_text(down)
    return directory


def _up(url: str, migrations: Path, **options: object):
    with MigratorSession(None, migrations, database_url_override=url) as session:
        return session.up(**options)


def _ledger(url: str) -> list[tuple[str, str | None]]:
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT version, archived_into FROM tb_confiture ORDER BY version"
        ).fetchall()


def _squash(migrations: Path, server_url: str) -> None:
    execute_squash(plan_squash(migrations, THROUGH, server_url=server_url), migrations)


def test_the_squash_writes_the_baseline_and_archives_the_rest(
    migrations: Path, test_db_url: str
) -> None:
    result = execute_squash(plan_squash(migrations, THROUGH, server_url=test_db_url), migrations)

    assert sorted(p.name for p in migrations.glob("*.sql")) == [
        f"{BASELINE}_squashed_baseline.down.sql",
        f"{BASELINE}_squashed_baseline.up.sql",
        "20260103000000_posts.down.sql",
        "20260103000000_posts.up.sql",
    ]
    assert sorted(p.name for p in (migrations / "archive").iterdir()) == [
        "20260101000000_users.down.sql",
        "20260101000000_users.up.sql",
        "20260102000000_email.down.sql",
        "20260102000000_email.up.sql",
    ]
    assert result.baseline.name == f"{BASELINE}_squashed_baseline.up.sql"


def test_with_delete_the_squashed_files_are_gone(migrations: Path, test_db_url: str) -> None:
    execute_squash(
        plan_squash(migrations, THROUGH, server_url=test_db_url), migrations, delete=True
    )

    assert not (migrations / "archive").exists()
    assert len(list(migrations.glob("*.up.sql"))) == 2


def test_a_database_that_applied_everything_records_the_baseline_without_running_it(
    migrations: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    url = fresh_database_factory("confiture_sq_env")
    assert _up(url, migrations).success
    with psycopg.connect(url) as conn:
        applied_at = conn.execute(
            "SELECT version, applied_at FROM tb_confiture ORDER BY version"
        ).fetchall()
    _squash(migrations, test_db_url)

    result = _up(url, migrations, verify_checksums=True)

    assert result.success and result.checksums_verified
    assert result.migrations_applied == []
    assert _ledger(url) == [
        ("20260101000000", BASELINE),
        ("20260102000000", BASELINE),
        (BASELINE, None),
        ("20260103000000", None),
    ]
    with psycopg.connect(url) as conn:
        kept = conn.execute(
            "SELECT version, applied_at FROM tb_confiture WHERE archived_into IS NOT NULL "
            "ORDER BY version"
        ).fetchall()
    assert kept == applied_at[:2]
    assert _up(url, migrations).migrations_applied == []


def test_a_database_that_stopped_short_of_the_cut_is_refused(
    migrations: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    url = fresh_database_factory("confiture_sq_short")
    assert _up(url, migrations, target="20260101000000").success
    _squash(migrations, test_db_url)

    with pytest.raises(ValidationError) as refused:
        _up(url, migrations)

    assert refused.value.error_code == "VALID_008"
    assert _ledger(url) == [("20260101000000", None)]


def test_a_database_whose_history_differs_from_the_files_is_refused(
    migrations: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    url = fresh_database_factory("confiture_sq_edit")
    assert _up(url, migrations).success
    (migrations / "20260101000000_users.up.sql").write_text(
        "CREATE TABLE users (id int PRIMARY KEY); -- edited after it was applied\n"
    )
    _squash(migrations, test_db_url)

    with pytest.raises(ValidationError) as refused:
        _up(url, migrations)

    assert refused.value.error_code == "VALID_008"
    assert (BASELINE, None) not in _ledger(url)


def test_a_fresh_database_applies_the_baseline_and_the_rest(
    migrations: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    _squash(migrations, test_db_url)
    url = fresh_database_factory("confiture_sq_fresh")

    result = _up(url, migrations)

    assert [m.version for m in result.migrations_applied] == [BASELINE, "20260103000000"]
    assert _ledger(url) == [(BASELINE, None), ("20260103000000", None)]


def test_a_dry_run_changes_no_ledger(
    migrations: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    url = fresh_database_factory("confiture_sq_dry")
    assert _up(url, migrations).success
    _squash(migrations, test_db_url)

    result = _up(url, migrations, dry_run=True)

    assert result.pending == []
    assert _ledger(url) == [
        ("20260101000000", None),
        ("20260102000000", None),
        ("20260103000000", None),
    ]


def test_the_ledger_step_runs_alone(
    migrations: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    url = fresh_database_factory("confiture_sq_alone")
    assert _up(url, migrations, target=THROUGH).success
    _squash(migrations, test_db_url)

    with MigratorSession(None, migrations, database_url_override=url) as session:
        recorded = session.record_squashed_baselines()

    assert recorded == [BASELINE]
    assert _ledger(url) == [
        ("20260101000000", BASELINE),
        ("20260102000000", BASELINE),
        (BASELINE, None),
    ]


def test_the_baseline_is_never_rolled_back(
    migrations: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    url = fresh_database_factory("confiture_sq_down")
    _squash(migrations, test_db_url)
    assert _up(url, migrations).success

    with MigratorSession(None, migrations, database_url_override=url) as session:
        with pytest.raises(Exception, match="squashed baseline"):
            session.down(steps=2)

    assert (BASELINE, None) in _ledger(url)
