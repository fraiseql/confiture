"""Integration tests for TestDbProvisioner (P2).

Requires a reachable local PostgreSQL (CONFITURE_TEST_DB_URL or localhost).
All databases created here use the ``confiture_p2_`` prefix and are dropped in
fixture teardown.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from confiture.core.schema_artifact import build_schema_artifact
from confiture.core.temp_database import _maintenance_url
from confiture.core.test_db import TemplateState, TestDbProvisioner
from confiture.exceptions import ConfigurationError

pytestmark = pytest.mark.integration

_SCHEMA = "CREATE TABLE widget (id int PRIMARY KEY, name text);"

_TEMPLATE = "confiture_p2_template"
_CLONE = "confiture_p2_clone"


def _server_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


def _drop_all(names: list[str]) -> None:
    with psycopg.connect(_maintenance_url(_server_url()), autocommit=True) as conn:
        for name in names:
            conn.execute(
                psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    psycopg.sql.Identifier(name)
                )
            )


@pytest.fixture
def provisioner() -> Iterator[TestDbProvisioner]:
    url = _server_url()
    try:
        with psycopg.connect(_maintenance_url(url), autocommit=True):
            pass
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")

    managed = [_TEMPLATE, _CLONE] + [f"{_CLONE}_{i}" for i in range(6)]
    _drop_all(managed)
    try:
        yield TestDbProvisioner(url)
    finally:
        _drop_all(managed)


def _tables(provisioner: TestDbProvisioner, db: str) -> set[str]:
    from confiture.core.temp_database import _replace_dbname

    with psycopg.connect(_replace_dbname(provisioner.server_url, db), autocommit=True) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    return {r[0] for r in rows}


def _show_synchronous_commit(provisioner: TestDbProvisioner, db: str) -> str:
    """Read ``synchronous_commit`` on a fresh connection to *db* (its effective default)."""
    from confiture.core.temp_database import _replace_dbname

    with psycopg.connect(_replace_dbname(provisioner.server_url, db), autocommit=True) as conn:
        return conn.execute("SHOW synchronous_commit").fetchone()[0]


def _per_db_settings(provisioner: TestDbProvisioner, db: str) -> list[str]:
    """Return the database-wide ``pg_db_role_setting`` entries for *db* (empty if none)."""
    with psycopg.connect(_maintenance_url(provisioner.server_url), autocommit=True) as conn:
        row = conn.execute(
            "SELECT s.setconfig FROM pg_db_role_setting s "
            "JOIN pg_database d ON s.setdatabase = d.oid "
            "WHERE d.datname = %s AND s.setrole = 0",
            (db,),
        ).fetchone()
    return list(row[0]) if row and row[0] else []


def _clone_tablespace(provisioner: TestDbProvisioner, db: str) -> str | None:
    """Return the spcname of the tablespace *db* lives in, or None if it is gone."""
    with psycopg.connect(_maintenance_url(provisioner.server_url), autocommit=True) as conn:
        row = conn.execute(
            "SELECT t.spcname FROM pg_database d "
            "JOIN pg_tablespace t ON d.dattablespace = t.oid WHERE d.datname = %s",
            (db,),
        ).fetchone()
    return row[0] if row else None


def _db_exists(provisioner: TestDbProvisioner, db: str) -> bool:
    with psycopg.connect(_maintenance_url(provisioner.server_url), autocommit=True) as conn:
        return (
            conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,)).fetchone()
            is not None
        )


class TestProvisionAndClone:
    def test_provision_template_ddl_path(self, provisioner: TestDbProvisioner) -> None:
        status = provisioner.provision_template(
            _TEMPLATE, schema_hash="hash-v1", schema_sql=_SCHEMA
        )
        assert status.state is TemplateState.CURRENT
        assert _tables(provisioner, _TEMPLATE) == {"widget"}

    def test_clone_has_template_tables(self, provisioner: TestDbProvisioner) -> None:
        provisioner.provision_template(_TEMPLATE, schema_hash="hash-v1", schema_sql=_SCHEMA)
        result = provisioner.clone(_TEMPLATE, _CLONE)
        assert result.target == _CLONE
        assert _tables(provisioner, _CLONE) == {"widget"}

    def test_provision_from_artifact(self, provisioner: TestDbProvisioner, tmp_path: Path) -> None:
        artifact = tmp_path / "p2.full.hash.pgdump"
        build_schema_artifact(
            server_url=provisioner.server_url,
            schema_sql=_SCHEMA,
            output_path=artifact,
            schema_hash="hash-v1",
        )
        status = provisioner.provision_template(
            _TEMPLATE, schema_hash="hash-v1", from_artifact=artifact
        )
        assert status.state is TemplateState.CURRENT
        assert _tables(provisioner, _TEMPLATE) == {"widget"}


class TestSynchronousCommit:
    def test_clone_sets_synchronous_commit_off(self, provisioner: TestDbProvisioner) -> None:
        provisioner.provision_template(_TEMPLATE, schema_hash="h", schema_sql=_SCHEMA)
        clone = f"{_CLONE}_0"
        provisioner.clone(_TEMPLATE, clone)  # sync_commit_off=True by default
        # A new connection to the clone observes the per-database default.
        assert _show_synchronous_commit(provisioner, clone) == "off"
        # The GUC rides on the clone only — the template carries no such per-db setting.
        assert not any(
            s.startswith("synchronous_commit=") for s in _per_db_settings(provisioner, _TEMPLATE)
        )

    def test_clone_opt_out_leaves_cluster_default(self, provisioner: TestDbProvisioner) -> None:
        provisioner.provision_template(_TEMPLATE, schema_hash="h", schema_sql=_SCHEMA)
        clone = f"{_CLONE}_1"
        provisioner.clone(_TEMPLATE, clone, sync_commit_off=False)
        # Opt-out leaves no per-database synchronous_commit override (cluster default applies).
        assert not any(
            s.startswith("synchronous_commit=") for s in _per_db_settings(provisioner, clone)
        )


class TestTablespaceUsable:
    """The cheap usability gate (#158). Absent/built-in paths run anywhere; the
    create-a-real-tablespace paths use the ``ram_tablespace`` fixture and skip
    cleanly where the environment can't host one."""

    def test_absent_returns_false(self, provisioner: TestDbProvisioner) -> None:
        assert provisioner.tablespace_usable("confiture_absent_ts_xyz") is False

    def test_builtin_returns_true(self, provisioner: TestDbProvisioner) -> None:
        # pg_default reports an empty LOCATION → always usable, no fs probe needed.
        assert provisioner.tablespace_usable("pg_default") is True

    def test_present_via_probe_returns_true(
        self, inplace_tablespace: tuple[TestDbProvisioner, str]
    ) -> None:
        # A real tablespace with a non-empty LOCATION exercises the pg_stat_file
        # probe path (not the empty-string built-in short-circuit).
        provisioner, name = inplace_tablespace
        assert provisioner.tablespace_usable(name) is True

    def test_present_tmpfs_returns_true(
        self, ram_tablespace: tuple[TestDbProvisioner, str, str]
    ) -> None:
        provisioner, name, _location = ram_tablespace
        assert provisioner.tablespace_usable(name) is True

    def test_false_when_location_removed(
        self, ram_tablespace: tuple[TestDbProvisioner, str, str]
    ) -> None:
        # Simulate the post-reboot tmpfs wipe: the catalog row + symlink survive,
        # the LOCATION dir is gone. The probe sees the absent path → False, no raise.
        provisioner, name, location = ram_tablespace
        shutil.rmtree(location, ignore_errors=True)
        assert provisioner.tablespace_usable(name) is False


class TestRamClone:
    """Clone into a tablespace + the on-disk fallback (#158). The happy path runs
    against a real in-place tablespace anywhere a superuser PG is reachable; the
    broken-tmpfs fallback uses the tmpfs fixture and skips where unavailable."""

    def test_clone_into_tablespace(
        self,
        provisioner: TestDbProvisioner,
        inplace_tablespace: tuple[TestDbProvisioner, str],
    ) -> None:
        _prov, tablespace = inplace_tablespace
        provisioner.provision_template(_TEMPLATE, schema_hash="h", schema_sql=_SCHEMA)
        clone = f"{_CLONE}_0"
        result = provisioner.clone(_TEMPLATE, clone, tablespace=tablespace)
        assert result.tablespace == tablespace
        # The clone genuinely landed in the tablespace…
        assert _clone_tablespace(provisioner, clone) == tablespace
        assert _tables(provisioner, clone) == {"widget"}
        # …and synchronous_commit=off still rides on the RAM clone.
        assert _show_synchronous_commit(provisioner, clone) == "off"

    def test_falls_back_to_disk_when_tablespace_absent(
        self, provisioner: TestDbProvisioner, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A clone targeting a tablespace that does not exist (UndefinedObject) must
        # degrade to an on-disk clone — the same safety net as a broken tmpfs, and
        # one that exercises the real fallback end-to-end on any reachable PG.
        provisioner.provision_template(_TEMPLATE, schema_hash="h", schema_sql=_SCHEMA)
        clone = f"{_CLONE}_2"
        with caplog.at_level(logging.WARNING):
            result = provisioner.clone(_TEMPLATE, clone, tablespace="confiture_no_such_ts")
        assert _db_exists(provisioner, clone)
        assert result.tablespace is None
        assert _clone_tablespace(provisioner, clone) == "pg_default"
        assert _tables(provisioner, clone) == {"widget"}
        assert any("falling back to an on-disk clone" in r.message for r in caplog.records)

    def test_falls_back_to_disk_when_tablespace_dir_broken(
        self,
        provisioner: TestDbProvisioner,
        ram_tablespace: tuple[TestDbProvisioner, str, str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _prov, tablespace, location = ram_tablespace
        provisioner.provision_template(_TEMPLATE, schema_hash="h", schema_sql=_SCHEMA)
        # Simulate a post-reboot tmpfs: catalog row + symlink survive, dir is gone.
        shutil.rmtree(location, ignore_errors=True)
        clone = f"{_CLONE}_1"
        with caplog.at_level(logging.WARNING):
            result = provisioner.clone(_TEMPLATE, clone, tablespace=tablespace)
        assert _db_exists(provisioner, clone)  # the suite is not broken
        assert result.tablespace is None  # it fell back to disk
        assert _clone_tablespace(provisioner, clone) == "pg_default"
        assert any("falling back to an on-disk clone" in r.message for r in caplog.records)


class TestRamSetup:
    """Real DROP+CREATE of a tmpfs tablespace. Skips where the box can't host one
    (not superuser, or no chown rights to hand /dev/shm to the PG OS user)."""

    def test_setup_creates_then_recreates_dropping_managed_clone(
        self,
        provisioner: TestDbProvisioner,
        ram_setup_env: tuple[TestDbProvisioner, str, str, str],
    ) -> None:
        ram_prov, name, location, owner = ram_setup_env

        first = ram_prov.setup_ram_tablespace(name, location, owner=owner)
        assert first.recreated is False
        assert first.action_required is False
        assert ram_prov.tablespace_usable(name) is True

        # A clone lands in the new tablespace…
        provisioner.provision_template(_TEMPLATE, schema_hash="h", schema_sql=_SCHEMA)
        clone = f"{_CLONE}_3"
        clone_result = provisioner.clone(_TEMPLATE, clone, tablespace=name)
        assert clone_result.tablespace == name
        assert _clone_tablespace(provisioner, clone) == name

        # …and a second ram-setup resets the tablespace, dropping that managed clone.
        second = ram_prov.setup_ram_tablespace(name, location, owner=owner)
        assert second.recreated is True
        assert clone in second.dropped_databases
        assert ram_prov.tablespace_usable(name) is True
        assert not _db_exists(provisioner, clone)


class TestStaleness:
    def test_status_current_then_stale(self, provisioner: TestDbProvisioner) -> None:
        provisioner.provision_template(_TEMPLATE, schema_hash="hash-v1", schema_sql=_SCHEMA)
        assert provisioner.template_status(_TEMPLATE, "hash-v1").state is TemplateState.CURRENT
        assert provisioner.template_status(_TEMPLATE, "hash-v2").state is TemplateState.STALE

    def test_status_absent_when_missing(self, provisioner: TestDbProvisioner) -> None:
        assert provisioner.template_status(_TEMPLATE, "hash-v1").state is TemplateState.ABSENT


class TestDropSafety:
    def test_drop_clone(self, provisioner: TestDbProvisioner) -> None:
        provisioner.provision_template(_TEMPLATE, schema_hash="h", schema_sql=_SCHEMA)
        provisioner.clone(_TEMPLATE, _CLONE)
        assert provisioner.drop(_CLONE) is True
        assert provisioner.template_status(_CLONE, "h").state is TemplateState.ABSENT

    def test_drop_missing_returns_false(self, provisioner: TestDbProvisioner) -> None:
        assert provisioner.drop(_CLONE) is False

    def test_drop_refuses_unmanaged_database(self, provisioner: TestDbProvisioner) -> None:
        # 'postgres' exists but is not confiture-managed → must refuse.
        with pytest.raises(ConfigurationError, match="not a confiture-managed"):
            provisioner.drop("postgres")


class TestConcurrencyAndPrune:
    def test_concurrent_clones_no_deadlock(self, provisioner: TestDbProvisioner) -> None:
        provisioner.provision_template(_TEMPLATE, schema_hash="h", schema_sql=_SCHEMA)
        errors: list[Exception] = []

        def _clone(i: int) -> None:
            try:
                provisioner.clone(_TEMPLATE, f"{_CLONE}_{i}")
            except Exception as e:  # noqa: BLE001 - recorded for assertion
                errors.append(e)

        threads = [threading.Thread(target=_clone, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, errors
        for i in range(6):
            assert _tables(provisioner, f"{_CLONE}_{i}") == {"widget"}

    def test_prune_drops_all_clones_of_template(self, provisioner: TestDbProvisioner) -> None:
        provisioner.provision_template(_TEMPLATE, schema_hash="h", schema_sql=_SCHEMA)
        provisioner.clone(_TEMPLATE, f"{_CLONE}_0")
        provisioner.clone(_TEMPLATE, f"{_CLONE}_1")

        dropped = provisioner.prune(_TEMPLATE)

        assert set(dropped) == {f"{_CLONE}_0", f"{_CLONE}_1"}
        # Template itself survives prune.
        assert provisioner.template_status(_TEMPLATE, "h").state is TemplateState.CURRENT
