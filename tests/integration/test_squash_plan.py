"""What ``migrate squash`` would write: the schema as of the cut, as one migration (#539).

The baseline is the database migrations 1..V build, dumped schema-only on a
scratch database; or, with ``--from-build``, the tree, once a drift check has
shown the two are one schema. Its header carries a digest of the archived
versions and checksums, the one fact the ledger step compares an environment's
ledger with.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture.core import live_catalog
from confiture.core.drift import SchemaDriftDetector
from confiture.core.migrator import MigratorSession
from confiture.core.sql_lexer import directives
from confiture.core.squash import archived_digest, plan_squash
from confiture.exceptions import MigrationError, ValidationError

pytestmark = pytest.mark.integration

MIGRATIONS = {
    "20260101000000_users": (
        "CREATE EXTENSION IF NOT EXISTS pgcrypto;\n"
        "CREATE TABLE users (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text);\n",
        "DROP TABLE users;\n",
    ),
    "20260102000000_email": (
        "ALTER TABLE users ADD COLUMN email text;\nCREATE INDEX users_email ON users (email);\n",
        "DROP INDEX users_email;\nALTER TABLE users DROP COLUMN email;\n",
    ),
    "20260103000000_posts": (
        "CREATE TABLE posts (id int PRIMARY KEY, author uuid REFERENCES users);\n",
        "DROP TABLE posts;\n",
    ),
}
THROUGH = "20260102000000"
TREE_AT_THROUGH = (
    "CREATE EXTENSION IF NOT EXISTS pgcrypto;\n"
    "CREATE TABLE users (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text, email text);\n"
    "CREATE INDEX users_email ON users (email);\n"
)


@pytest.fixture
def migrations(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    for stem, (up, down) in MIGRATIONS.items():
        (directory / f"{stem}.up.sql").write_text(up)
        (directory / f"{stem}.down.sql").write_text(down)
    return directory


def _model(url: str) -> object:
    with psycopg.connect(url) as conn:
        return live_catalog.read(conn, schemas=["public"], routines=True, views=True, triggers=True)


def test_the_plan_names_what_it_archives(migrations: Path, test_db_url: str) -> None:
    plan = plan_squash(migrations, THROUGH, server_url=test_db_url)

    assert plan.versions == ("20260101000000", THROUGH)
    assert sorted(p.name for p in plan.archived) == [
        "20260101000000_users.down.sql",
        "20260101000000_users.up.sql",
        "20260102000000_email.down.sql",
        "20260102000000_email.up.sql",
    ]
    assert plan.version == "20260102000001"
    assert plan.baseline_name == "20260102000001_squashed_baseline.up.sql"
    assert plan.source == "replay"


def test_the_baseline_plus_the_rest_builds_the_same_schema(
    migrations: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    plan = plan_squash(migrations, THROUGH, server_url=test_db_url)
    from_history = fresh_database_factory("confiture_sq_hist")
    from_baseline = fresh_database_factory("confiture_sq_base")
    with MigratorSession(None, migrations, database_url_override=from_history) as session:
        assert session.up().success
    with psycopg.connect(from_baseline) as conn:
        conn.execute(plan.sql)
        conn.execute(MIGRATIONS["20260103000000_posts"][0])

    with psycopg.connect(from_baseline) as conn:
        report = SchemaDriftDetector(conn).compare_schemas(
            _model(from_history), _model(from_baseline), objects=True
        )
    assert report.drift_items == []


def test_the_baseline_leaves_the_ledger_and_the_session_alone(
    migrations: Path, test_db_url: str
) -> None:
    sql = plan_squash(migrations, THROUGH, server_url=test_db_url).sql

    assert "tb_confiture" not in sql
    assert "confiture_lock_holder" not in sql
    assert "set_config" not in sql
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in sql


def test_the_header_is_a_directive_carrying_the_cut_and_the_digest(
    migrations: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    plan = plan_squash(migrations, THROUGH, server_url=test_db_url)
    applied = fresh_database_factory("confiture_sq_ledger")
    with MigratorSession(None, migrations, database_url_override=applied) as session:
        assert session.up().success
    with psycopg.connect(applied) as conn:
        rows = conn.execute(
            "SELECT version, checksum FROM tb_confiture WHERE version <= %s", (THROUGH,)
        ).fetchall()

    (header,) = [d for d in directives(plan.sql) if d.name == "squashed-baseline"]
    assert header.argument == f"through={THROUGH} versions=2 digest={plan.digest}"
    assert plan.digest == archived_digest(rows)


def test_a_cut_that_is_no_migration_is_refused(migrations: Path, test_db_url: str) -> None:
    with pytest.raises(MigrationError):
        plan_squash(migrations, "20260101500000", server_url=test_db_url)


def test_no_free_version_is_refused_and_a_given_one_is_used(
    migrations: Path, test_db_url: str
) -> None:
    (migrations / "20260102000001_hotfix.up.sql").write_text("SELECT 1;\n")
    (migrations / "20260102000001_hotfix.down.sql").write_text("SELECT 1;\n")

    with pytest.raises(ValidationError) as refused:
        plan_squash(migrations, THROUGH, server_url=test_db_url)
    assert refused.value.error_code == "VALID_007"

    plan = plan_squash(migrations, THROUGH, server_url=test_db_url, version="20260102000000a")
    assert plan.version == "20260102000000a"


def test_from_build_uses_the_tree_once_it_is_proven_equal(
    migrations: Path, test_db_url: str
) -> None:
    plan = plan_squash(migrations, THROUGH, server_url=test_db_url, build_sql=TREE_AT_THROUGH)

    assert plan.source == "build"
    assert TREE_AT_THROUGH in plan.sql


def test_from_build_refuses_a_tree_that_is_not_the_state_at_the_cut(
    migrations: Path, test_db_url: str
) -> None:
    ahead = TREE_AT_THROUGH + "CREATE TABLE posts (id int PRIMARY KEY);\n"

    with pytest.raises(ValidationError) as refused:
        plan_squash(migrations, THROUGH, server_url=test_db_url, build_sql=ahead)

    assert refused.value.error_code == "VALID_006"
    assert "posts" in str(refused.value)
