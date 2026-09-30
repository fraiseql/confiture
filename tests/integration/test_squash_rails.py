"""What ``migrate squash`` checks before it cuts: every environment it can reach (#539).

``migrate up`` refuses a baseline on a database that holds part of its history
(``VALID_008``), but only when that database deploys. The squash asks each
``db/environments/*.yaml`` first and refuses (``VALID_009``, naming it) when one
has a squashed version pending, applied the cut more recently than
``squash.min_age_days`` in ``db/project.yaml``, or has an online migration up to
the cut unfinished. An environment listed in ``squash.skip_environments`` is not
asked; one that cannot be reached, and is not listed, refuses.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
import yaml

from confiture.core.migrator import MigratorSession
from confiture.core.squash import check_environments
from confiture.core.step_runner import CheckpointStore
from confiture.exceptions import ValidationError

pytestmark = pytest.mark.integration

MIGRATIONS = {
    "20260101000000_users": ("CREATE TABLE users (id int PRIMARY KEY);\n", "DROP TABLE users;\n"),
    "20260102000000_email": (
        "ALTER TABLE users ADD COLUMN email text;\n",
        "ALTER TABLE users DROP COLUMN email;\n",
    ),
}
VERSIONS = ("20260101000000", "20260102000000")
THROUGH = VERSIONS[1]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    migrations = tmp_path / "db/migrations"
    migrations.mkdir(parents=True)
    (tmp_path / "db/environments").mkdir()
    (tmp_path / "db/schema").mkdir()
    for stem, (up, down) in MIGRATIONS.items():
        (migrations / f"{stem}.up.sql").write_text(up)
        (migrations / f"{stem}.down.sql").write_text(down)
    return tmp_path


def _environment(project: Path, name: str, url: str) -> None:
    (project / f"db/environments/{name}.yaml").write_text(
        yaml.safe_dump({"name": name, "database_url": url, "include_dirs": ["db/schema"]})
    )


def _project_yaml(project: Path, **squash: object) -> None:
    (project / "db/project.yaml").write_text(yaml.safe_dump({"squash": squash}))


def _applied(
    factory: Callable[[str], str], project: Path, *, target: str | None = None, days_ago: int = 200
) -> str:
    url = factory("confiture_rail")
    with MigratorSession(None, project / "db/migrations", database_url_override=url) as session:
        assert session.up(target=target).success
    with psycopg.connect(url) as conn:
        conn.execute(
            "UPDATE tb_confiture SET applied_at = now() - make_interval(days => %s)", (days_ago,)
        )
    return url


def _check(project: Path) -> list:
    return check_environments(project, VERSIONS, THROUGH)


def test_environments_that_applied_the_history_long_ago_pass(
    project: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    _environment(project, "production", _applied(fresh_database_factory, project))
    _environment(project, "staging", _applied(fresh_database_factory, project))

    checked = _check(project)

    assert [(c.name, c.skipped) for c in checked] == [("production", False), ("staging", False)]


def test_an_environment_with_a_squashed_version_pending_is_refused_by_name(
    project: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    _environment(project, "production", _applied(fresh_database_factory, project))
    _environment(project, "staging", _applied(fresh_database_factory, project, target=VERSIONS[0]))

    with pytest.raises(ValidationError) as refused:
        _check(project)

    assert refused.value.error_code == "VALID_009"
    assert "staging" in str(refused.value)
    assert VERSIONS[1] in str(refused.value)


def test_a_cut_applied_too_recently_is_refused(
    project: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    _environment(project, "production", _applied(fresh_database_factory, project, days_ago=10))
    _project_yaml(project, min_age_days=30)

    with pytest.raises(ValidationError) as refused:
        _check(project)

    assert refused.value.error_code == "VALID_009"
    assert "30 days" in str(refused.value)


def test_min_age_zero_accepts_a_fresh_cut(
    project: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    _environment(project, "production", _applied(fresh_database_factory, project, days_ago=0))
    _project_yaml(project, min_age_days=0)

    assert [c.name for c in _check(project)] == ["production"]


def test_an_unreachable_environment_refuses_unless_skipped(
    project: Path, fresh_database_factory: Callable[[str], str], test_db_url: str
) -> None:
    _environment(project, "production", _applied(fresh_database_factory, project))
    _environment(project, "ci", test_db_url.rsplit("/", 1)[0] + "/confiture_no_such_db")

    with pytest.raises(ValidationError) as refused:
        _check(project)
    assert "ci" in str(refused.value)

    _project_yaml(project, skip_environments=["ci"])
    assert [(c.name, c.skipped) for c in _check(project)] == [
        ("ci", True),
        ("production", False),
    ]


def test_an_unfinished_online_migration_up_to_the_cut_is_refused(
    project: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    url = _applied(fresh_database_factory, project)
    _environment(project, "production", url)
    with psycopg.connect(url) as conn:
        store = CheckpointStore(conn, "tb_confiture_steps")
        store.ensure()
        store.start(VERSIONS[0], 0, "backfill")
        conn.commit()

    with pytest.raises(ValidationError) as refused:
        _check(project)

    assert "online" in str(refused.value)


def test_with_no_environment_asked_the_version_s_own_date_is_its_age(project: Path) -> None:
    _project_yaml(project, min_age_days=30)

    assert _check(project) == []

    _project_yaml(project, min_age_days=365 * 100)
    with pytest.raises(ValidationError):
        _check(project)


def test_an_undated_version_with_no_environment_asked_is_refused(project: Path) -> None:
    with pytest.raises(ValidationError) as refused:
        check_environments(project, ("001", "002"), "002")

    assert "age" in str(refused.value)


def test_a_refusal_never_echoes_an_environment_s_password(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """libpq repeats a malformed conninfo in its error, password included."""
    from confiture.core import squash

    def echoing(url: str, **_kwargs: object) -> None:
        raise psycopg.OperationalError(f'missing "=" after "{url}" in connection info string')

    _environment(project, "production", "postgresql://user:secret@db.example.internal:5432/app")
    monkeypatch.setattr(squash.psycopg, "connect", echoing)

    with pytest.raises(ValidationError) as refused:
        _check(project)

    assert "production: cannot be asked" in str(refused.value)
    assert "secret@" not in str(refused.value)
