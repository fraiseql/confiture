"""Shared integration-test scaffolding for RAM-tablespace provisioning (#158).

Two fixtures supply a live tablespace to the Phase 02–04 integration tests:

- :func:`ram_tablespace` builds a real **tmpfs** (``/dev/shm``) tablespace — the
  production target. It **skips cleanly** whenever the environment cannot host
  one: a non-superuser connection, no reachable database, or (the common
  multi-user case) a PostgreSQL server whose OS user cannot claim a freshly
  created ``/dev/shm`` directory because the test process lacks chown rights.
  That skip is not a gap — it is precisely the environment Phase 03's on-disk
  fallback exists to cover.

- :func:`inplace_tablespace` builds an **in-place** tablespace via the PG 15+
  ``allow_in_place_tablespaces`` developer GUC. An in-place tablespace lives
  under the data directory and is owned by the PG server OS user automatically,
  so it needs no external dir/chown and runs on an ordinary superuser dev box.
  It exercises confiture's *clone-into-named-tablespace* plumbing for real; the
  RAM-specific concerns (tmpfs, post-reboot breakage) belong to
  :func:`ram_tablespace` and the unit-level fallback tests.
"""

from __future__ import annotations

import os
import pwd
import shutil
from collections.abc import Iterator

import psycopg
import psycopg.errors
import psycopg.sql
import pytest

from confiture.core.temp_database import _maintenance_url
from confiture.core.test_db import TestDbProvisioner

_RAM_TABLESPACE = "confiture_ram_it"
_RAM_LOCATION = "/dev/shm/confiture_ram_it"
_INPLACE_TABLESPACE = "confiture_inplace_it"
_RAMSETUP_TABLESPACE = "confiture_ramsetup_it"
_RAMSETUP_LOCATION = "/dev/shm/confiture_ramsetup_it"


def _ram_server_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


def _is_superuser(conn: psycopg.Connection) -> bool:
    return conn.execute("SELECT current_setting('is_superuser')").fetchone()[0] == "on"


def _drop_dbs_in_tablespace(conn: psycopg.Connection, name: str) -> None:
    rows = conn.execute(
        "SELECT d.datname FROM pg_database d "
        "JOIN pg_tablespace t ON d.dattablespace = t.oid WHERE t.spcname = %s",
        (name,),
    ).fetchall()
    for (db,) in rows:
        conn.execute(
            psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                psycopg.sql.Identifier(db)
            )
        )


def _drop_tablespace(url: str, name: str) -> None:
    """Drop a tablespace and every database living in it (best-effort)."""
    try:
        with psycopg.connect(_maintenance_url(url), autocommit=True) as conn:
            _drop_dbs_in_tablespace(conn, name)
            conn.execute(
                psycopg.sql.SQL("DROP TABLESPACE IF EXISTS {}").format(psycopg.sql.Identifier(name))
            )
    except psycopg.Error:
        pass


def _teardown_tmpfs_tablespace(url: str, name: str, location: str) -> None:
    _drop_tablespace(url, name)
    shutil.rmtree(location, ignore_errors=True)


def _try_chown_to_pg(conn: psycopg.Connection, location: str) -> None:
    """Hand *location* to the PG server's OS user if we can (best-effort).

    When the client and server share a filesystem and the test runs with chown
    rights, this lets ``CREATE TABLESPACE`` claim the dir. When it can't (typical
    dev box), the subsequent CREATE fails and the fixture skips.
    """
    try:
        datadir = conn.execute("SHOW data_directory").fetchone()[0]
        st = os.stat(datadir)
        if st.st_uid != os.getuid():
            os.chown(location, st.st_uid, st.st_gid)
    except (OSError, psycopg.Error):
        pass


def _provision_tmpfs_tablespace(url: str, name: str, location: str) -> bool:
    """Create a tmpfs tablespace; return True on success, False if the env can't."""
    _teardown_tmpfs_tablespace(url, name, location)  # reap any leftover
    try:
        os.makedirs(location, mode=0o700, exist_ok=True)
    except OSError:
        return False
    with psycopg.connect(_maintenance_url(url), autocommit=True) as conn:
        _try_chown_to_pg(conn, location)
        try:
            conn.execute(
                psycopg.sql.SQL("CREATE TABLESPACE {} LOCATION {}").format(
                    psycopg.sql.Identifier(name), psycopg.sql.Literal(location)
                )
            )
        except (psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedFile, OSError):
            shutil.rmtree(location, ignore_errors=True)
            return False
    return True


@pytest.fixture
def ram_tablespace() -> Iterator[tuple[TestDbProvisioner, str, str]]:
    """Yield ``(provisioner, tablespace_name, location)`` for a live tmpfs tablespace.

    Skips cleanly when the environment cannot host one (see module docstring).
    Shared scaffolding for the Phase 02–04 integration tests.
    """
    url = _ram_server_url()
    try:
        with psycopg.connect(_maintenance_url(url), autocommit=True) as probe:
            superuser = _is_superuser(probe)
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")
    if not superuser:
        pytest.skip("CREATE TABLESPACE requires a superuser connection")

    if not _provision_tmpfs_tablespace(url, _RAM_TABLESPACE, _RAM_LOCATION):
        pytest.skip("environment cannot host a tmpfs tablespace (no chown rights / remote PG)")

    provisioner = TestDbProvisioner(url)
    try:
        yield provisioner, _RAM_TABLESPACE, _RAM_LOCATION
    finally:
        _teardown_tmpfs_tablespace(url, _RAM_TABLESPACE, _RAM_LOCATION)


@pytest.fixture
def inplace_tablespace() -> Iterator[tuple[TestDbProvisioner, str]]:
    """Yield ``(provisioner, tablespace_name)`` for a live in-place tablespace.

    Runs on an ordinary superuser dev box (no external dir/chown). Skips when not
    superuser or when ``allow_in_place_tablespaces`` is unavailable (PostgreSQL
    older than 15).
    """
    url = _ram_server_url()
    try:
        with psycopg.connect(_maintenance_url(url), autocommit=True) as conn:
            if not _is_superuser(conn):
                pytest.skip("in-place tablespace requires a superuser connection")
            _drop_tablespace(url, _INPLACE_TABLESPACE)
            try:
                conn.execute("SET allow_in_place_tablespaces = on")
            except psycopg.errors.UndefinedObject:
                pytest.skip("allow_in_place_tablespaces unavailable (PostgreSQL < 15)")
            conn.execute(
                psycopg.sql.SQL("CREATE TABLESPACE {} LOCATION ''").format(
                    psycopg.sql.Identifier(_INPLACE_TABLESPACE)
                )
            )
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")

    provisioner = TestDbProvisioner(url)
    try:
        yield provisioner, _INPLACE_TABLESPACE
    finally:
        _drop_tablespace(url, _INPLACE_TABLESPACE)


@pytest.fixture
def ram_setup_env() -> Iterator[tuple[TestDbProvisioner, str, str, str]]:
    """Yield ``(provisioner, tablespace_name, location, owner)`` for ram-setup tests.

    Resolves the PG server's OS user from its data directory and prepares a fresh,
    PG-owned, empty ``/dev/shm`` directory so ``setup_ram_tablespace`` can create a
    real tablespace. Skips cleanly where it can't (not superuser, or the test
    process lacks the chown rights to hand the dir to the PG user).
    """
    url = _ram_server_url()
    try:
        with psycopg.connect(_maintenance_url(url), autocommit=True) as conn:
            if not _is_superuser(conn):
                pytest.skip("ram-setup requires a superuser connection")
            datadir = conn.execute("SHOW data_directory").fetchone()[0]
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")

    try:
        st = os.stat(datadir)
        owner = pwd.getpwuid(st.st_uid).pw_name
    except (OSError, KeyError):
        pytest.skip("cannot resolve the PostgreSQL server OS user from its data directory")

    _drop_tablespace(url, _RAMSETUP_TABLESPACE)
    shutil.rmtree(_RAMSETUP_LOCATION, ignore_errors=True)
    try:
        os.makedirs(_RAMSETUP_LOCATION, mode=0o700, exist_ok=True)
        if st.st_uid != os.getuid():
            os.chown(_RAMSETUP_LOCATION, st.st_uid, st.st_gid)
    except (OSError, PermissionError):
        shutil.rmtree(_RAMSETUP_LOCATION, ignore_errors=True)
        pytest.skip("cannot prepare a PG-owned tmpfs dir (no chown rights)")

    provisioner = TestDbProvisioner(url)
    try:
        yield provisioner, _RAMSETUP_TABLESPACE, _RAMSETUP_LOCATION, owner
    finally:
        _teardown_tmpfs_tablespace(url, _RAMSETUP_TABLESPACE, _RAMSETUP_LOCATION)
