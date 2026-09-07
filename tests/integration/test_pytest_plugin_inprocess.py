"""The confiture pytest plugin's fixtures, exercised by an inner pytest session in-process.

``tests/integration/test_pytest_worker_db.py`` proves the xdist isolation with real
subprocesses; a subprocess is invisible to coverage, so this module runs the same kind
of inner project through ``pytester.runpytest_inprocess`` — the fixtures execute in
this process against the local test server: template build, per-worker clone, the
sandbox, validator and snapshotter, and the session-scoped facts.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from tests.conftest import DEFAULT_TEST_DB_URL, resolve_db_url

from confiture.core.temp_database import _maintenance_url

pytestmark = pytest.mark.integration

_TEMPLATE = "confiture_plugin_inproc_template"
_SCHEMA = "CREATE TABLE widget (id int PRIMARY KEY, label text NOT NULL);"


def _server_url() -> str:
    return resolve_db_url("CONFITURE_TEST_DB_URL", DEFAULT_TEST_DB_URL)


def _drop_like(prefix: str) -> None:
    with psycopg.connect(_maintenance_url(_server_url()), autocommit=True) as conn:
        rows = conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE %s", (prefix + "%",)
        ).fetchall()
        for (name,) in rows:
            conn.execute(
                psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    psycopg.sql.Identifier(name)
                )
            )


@pytest.fixture
def clean_server() -> Iterator[None]:
    try:
        with psycopg.connect(_maintenance_url(_server_url()), autocommit=True):
            pass
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")
    _drop_like(_TEMPLATE)
    try:
        yield
    finally:
        _drop_like(_TEMPLATE)


def _write_project(root: Path) -> None:
    (root / "db" / "schema").mkdir(parents=True)
    (root / "db" / "schema" / "01_widget.sql").write_text(_SCHEMA)
    (root / "db" / "migrations").mkdir(parents=True)
    (root / "db" / "environments").mkdir(parents=True)
    (root / "db" / "environments" / "local.yaml").write_text(
        f'name: local\ndatabase_url: "{_server_url()}"\ninclude_dirs:\n  - db/schema\n'
    )
    # The confiture plugin is auto-loaded through its pytest11 entry point.
    (root / "conftest.py").write_text(
        "from pathlib import Path\n"
        "import pytest\n"
        "@pytest.fixture(scope='session')\n"
        "def confiture_project_dir():\n"
        "    return Path(__file__).parent\n"
        "@pytest.fixture(scope='session')\n"
        f"def confiture_template_name():\n    return {_TEMPLATE!r}\n"
    )


def test_plugin_fixtures_run_in_process(
    pytester: pytest.Pytester, clean_server: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONFITURE_TEST_DB_URL", _server_url())
    monkeypatch.delenv("CONFITURE_TEST_RAM_TABLESPACE", raising=False)
    _write_project(pytester.path)
    pytester.makepyfile(
        test_inner="""
        import psycopg

        def test_worker_db_is_a_clone_of_the_template(confiture_worker_db, confiture_template_db):
            assert confiture_template_db == __TEMPLATE__
            with psycopg.connect(confiture_worker_db, autocommit=True) as conn:
                tables = {r[0] for r in conn.execute(
                    "select tablename from pg_tables where schemaname='public'"
                ).fetchall()}
            assert tables == {"widget"}

        def test_session_facts(confiture_env, confiture_worker_id, confiture_ci,
                               confiture_ram_tablespace, confiture_ram_tablespace_usable,
                               confiture_test_server_url):
            assert confiture_env == "local"
            assert confiture_worker_id is None
            assert isinstance(confiture_ci, bool)
            assert confiture_ram_tablespace is None
            assert confiture_ram_tablespace_usable is None
            assert confiture_test_server_url.startswith("postgres")

        def test_sandbox_validator_and_snapshotter(confiture_sandbox, confiture_validator,
                                                    confiture_snapshotter, tb_confiture_dir):
            assert tb_confiture_dir.as_posix() == "db/migrations"
            assert confiture_validator is not None
            assert confiture_snapshotter is not None
            assert confiture_sandbox.connection is not None
        """.replace("__TEMPLATE__", repr(_TEMPLATE))
    )
    result = pytester.runpytest_inprocess("-p", "no:cacheprovider", "-q")
    result.assert_outcomes(passed=3)
