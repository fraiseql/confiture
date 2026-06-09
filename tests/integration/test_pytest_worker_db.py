"""Integration tests for per-worker xdist provisioning (P3).

Covers single-flight template build (`ensure_template`) and a REAL `pytest -n2`
subprocess run exercising the `confiture_worker_db` fixture under genuine
parallelism (not just a hand-set PYTEST_XDIST_WORKER).

Requires a reachable local PostgreSQL.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from confiture.core.temp_database import _maintenance_url, _replace_dbname
from confiture.core.test_db import TemplateState, TestDbProvisioner

pytestmark = pytest.mark.integration

_SCHEMA = "CREATE TABLE widget (id int PRIMARY KEY);"
_TEMPLATE = "confiture_p3_template"


def _server_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


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
    url = _server_url()
    try:
        with psycopg.connect(_maintenance_url(url), autocommit=True):
            pass
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")
    _drop_like(_TEMPLATE)
    try:
        yield
    finally:
        _drop_like(_TEMPLATE)


class TestEnsureTemplateSingleFlight:
    def test_concurrent_ensure_builds_once_and_is_consistent(self, clean_server: None) -> None:
        provisioner = TestDbProvisioner(_server_url())
        errors: list[Exception] = []

        def _ensure() -> None:
            try:
                provisioner.ensure_template(_TEMPLATE, schema_hash="h1", schema_sql=_SCHEMA)
            except Exception as e:  # noqa: BLE001 - recorded for assertion
                errors.append(e)

        threads = [threading.Thread(target=_ensure) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, errors
        status = provisioner.template_status(_TEMPLATE, "h1")
        assert status.state is TemplateState.CURRENT
        with psycopg.connect(_replace_dbname(_server_url(), _TEMPLATE), autocommit=True) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                ).fetchall()
            }
        assert tables == {"widget"}

    def test_ensure_is_noop_when_current(self, clean_server: None) -> None:
        provisioner = TestDbProvisioner(_server_url())
        provisioner.ensure_template(_TEMPLATE, schema_hash="h1", schema_sql=_SCHEMA)
        # Second call with the same hash must observe CURRENT and not rebuild.
        status = provisioner.ensure_template(_TEMPLATE, schema_hash="h1", schema_sql=_SCHEMA)
        assert status.state is TemplateState.CURRENT


def _write_inner_project(root: Path, server_url: str) -> None:
    (root / "db" / "schema").mkdir(parents=True)
    (root / "db" / "schema" / "01.sql").write_text(_SCHEMA)
    (root / "db" / "environments").mkdir(parents=True)
    (root / "db" / "environments" / "local.yaml").write_text(
        f'name: local\ndatabase_url: "{server_url}"\ninclude_dirs:\n  - db/schema\n'
    )
    # No `pytest_plugins = [...]`: the confiture plugin is already auto-loaded
    # via its pytest11 entry point, so re-declaring it raises a double-register
    # error. This mirrors how a real consumer (confiture installed) sees it.
    (root / "conftest.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import pytest\n"
        "@pytest.fixture(scope='session')\n"
        "def confiture_project_dir():\n"
        "    return Path(__file__).parent\n"
        "@pytest.fixture(scope='session')\n"
        "def confiture_template_name():\n"
        f"    return {_TEMPLATE!r}\n"
        "@pytest.fixture(scope='session')\n"
        "def confiture_test_server_url():\n"
        "    return os.environ['CONFITURE_TEST_DB_URL']\n"
    )
    (root / "test_inner.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import psycopg\n"
        "import pytest\n"
        "@pytest.mark.parametrize('i', range(8))\n"
        "def test_worker_db_is_isolated_clone(confiture_worker_db, i):\n"
        "    with psycopg.connect(confiture_worker_db, autocommit=True) as conn:\n"
        "        dbname = conn.execute('select current_database()').fetchone()[0]\n"
        "        tables = {r[0] for r in conn.execute(\n"
        "            \"select tablename from pg_tables where schemaname='public'\"\n"
        "        ).fetchall()}\n"
        "    assert 'widget' in tables\n"
        "    Path(os.environ['P3_RECORD_DIR'], dbname).write_text('ok')\n"
    )


def test_real_xdist_n2_gives_each_worker_its_own_db(clean_server: None, tmp_path: Path) -> None:
    """A genuine `pytest -n2` run yields two distinct, isolated worker databases."""
    pytest.importorskip("xdist")

    inner = tmp_path / "proj"
    inner.mkdir()
    _write_inner_project(inner, _server_url())
    record_dir = tmp_path / "records"
    record_dir.mkdir()

    env = {
        **os.environ,
        "CONFITURE_TEST_DB_URL": _server_url(),
        "P3_RECORD_DIR": str(record_dir),
    }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(inner), "-n2", "-p", "no:cacheprovider", "-q"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(inner),
    )

    assert result.returncode == 0, f"inner pytest failed:\n{result.stdout}\n{result.stderr}"

    seen = {p.name for p in record_dir.iterdir()}
    # Two workers → two distinct, suffixed worker databases.
    assert len(seen) >= 2, f"expected >=2 worker DBs, saw {seen}"
    assert all(name.startswith(f"{_TEMPLATE}_db_gw") for name in seen), seen


def _write_inner_project_recording_tablespace(root: Path, server_url: str) -> None:
    """Inner project whose test records the *tablespace* its worker DB landed in."""
    (root / "db" / "schema").mkdir(parents=True)
    (root / "db" / "schema" / "01.sql").write_text(_SCHEMA)
    (root / "db" / "environments").mkdir(parents=True)
    (root / "db" / "environments" / "local.yaml").write_text(
        f'name: local\ndatabase_url: "{server_url}"\ninclude_dirs:\n  - db/schema\n'
    )
    (root / "conftest.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import pytest\n"
        "@pytest.fixture(scope='session')\n"
        "def confiture_project_dir():\n"
        "    return Path(__file__).parent\n"
        "@pytest.fixture(scope='session')\n"
        "def confiture_template_name():\n"
        f"    return {_TEMPLATE!r}\n"
        "@pytest.fixture(scope='session')\n"
        "def confiture_test_server_url():\n"
        "    return os.environ['CONFITURE_TEST_DB_URL']\n"
    )
    (root / "test_inner.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "import psycopg\n"
        "import pytest\n"
        "@pytest.mark.parametrize('i', range(6))\n"
        "def test_worker_db_lands_in_ram(confiture_worker_db, i):\n"
        "    with psycopg.connect(confiture_worker_db, autocommit=True) as conn:\n"
        "        dbname = conn.execute('select current_database()').fetchone()[0]\n"
        "        ts = conn.execute(\n"
        "            'select t.spcname from pg_database d join pg_tablespace t '\n"
        "            'on d.dattablespace = t.oid where d.datname = current_database()'\n"
        "        ).fetchone()[0]\n"
        "    Path(os.environ['P3_RECORD_DIR'], dbname).write_text(ts)\n"
    )


def test_real_xdist_n2_clones_into_ram_tablespace(
    clean_server: None,
    tmp_path: Path,
    inplace_tablespace: tuple[object, str],
) -> None:
    """A genuine `pytest -n2` run places every worker DB in the configured tablespace.

    Exercises the whole Phase 05 chain under real parallelism: the env var →
    ``confiture_ram_tablespace`` → usability memo → ``clone(tablespace=…)``. Uses a
    real in-place tablespace so it runs on an ordinary superuser box.
    """
    pytest.importorskip("xdist")
    _ram_prov, tablespace = inplace_tablespace

    inner = tmp_path / "proj"
    inner.mkdir()
    _write_inner_project_recording_tablespace(inner, _server_url())
    record_dir = tmp_path / "records"
    record_dir.mkdir()

    env = {
        **os.environ,
        "CONFITURE_TEST_DB_URL": _server_url(),
        "P3_RECORD_DIR": str(record_dir),
        "CONFITURE_TEST_RAM_TABLESPACE": tablespace,
    }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(inner), "-n2", "-p", "no:cacheprovider", "-q"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(inner),
    )

    assert result.returncode == 0, f"inner pytest failed:\n{result.stdout}\n{result.stderr}"
    # No opaque worker INTERNALERROR (the pytest.exit() gotcha).
    assert "INTERNALERROR" not in result.stdout + result.stderr

    recorded = {p.name: p.read_text() for p in record_dir.iterdir()}
    assert len(recorded) >= 2, f"expected >=2 worker DBs, saw {recorded}"
    # Every worker clone landed in the RAM tablespace.
    assert all(ts == tablespace for ts in recorded.values()), recorded
