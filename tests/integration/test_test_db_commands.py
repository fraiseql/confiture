"""``confiture test-db`` list, status, drop, prune and ram-setup, run by their command lines.

Each test provisions its own template and clones through the CLI
(``test-db provision-template`` / ``test-db clone``) and then checks what the
command under test did against ``pg_database`` and ``pg_tablespace``, not only
its exit code:

- ``list`` reports the templates and clones a provision created, with what each
  was stamped with, and leaves out a database confiture does not manage;
- ``status`` reports a template current, stale once the DDL changes, and absent
  when it was never provisioned — exiting 1 for the last two;
- ``drop`` removes exactly the database it names, refuses one confiture does not
  manage unless ``--force``, and reports a name that does not exist;
- ``prune`` drops every clone of its template and keeps the template, another
  template's clones and an unmanaged database;
- ``ram-setup`` refuses a LOCATION outside tmpfs, prints the privileged command
  when it cannot hand the directory to the server's OS user, and — where the host
  can hold a tmpfs tablespace — creates it, then resets it and drops the managed
  clone living in it.

The databases are server-global and other suites run at the same time, so every
name carries a per-test ``confiture_tdbcli_<hex>`` prefix, every assertion about
the server reads only names with that prefix, and teardown drops only the names
the test created. ``prune`` is scoped by its template, which carries the prefix.
"""

from __future__ import annotations

import json
import os
import pwd
import shutil
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
import psycopg.sql
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.test_db import TestDbProvisioner
from confiture.error_codes import FINDINGS, exit_code_of

pytestmark = pytest.mark.integration

runner = CliRunner()

_SHM = Path("/dev/shm")
_WIDGET_DDL = "CREATE TABLE widget (id BIGINT PRIMARY KEY, name TEXT);\n"

#: ``ram-setup``'s exit code when a privileged OS step is required (the precondition bucket).
_ACTION_REQUIRED = 5


@dataclass
class Project:
    """A tiny DDL project, the server it provisions on, and the databases it may create."""

    root: Path
    url: str
    maintenance_url: str
    prefix: str
    created: list[str] = field(default_factory=list)

    def name(self, suffix: str) -> str:
        """A database name owned by this test, recorded so teardown drops it."""
        db_name = f"{self.prefix}_{suffix}"
        self.created.append(db_name)
        return db_name

    def datnames(self) -> set[str]:
        """The databases on the server that carry this test's prefix."""
        with psycopg.connect(self.maintenance_url, autocommit=True) as conn:
            rows = conn.execute(
                "SELECT datname FROM pg_database WHERE starts_with(datname, %s)",
                (f"{self.prefix}_",),
            ).fetchall()
        return {row[0] for row in rows}

    def create_unmanaged(self, suffix: str) -> str:
        """A plain database with no confiture marker, as someone else's would be."""
        db_name = self.name(suffix)
        with psycopg.connect(self.maintenance_url, autocommit=True) as conn:
            conn.execute(
                psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(db_name))
            )
        return db_name

    def drop_created(self) -> None:
        with psycopg.connect(self.maintenance_url, autocommit=True) as conn:
            for db_name in self.created:
                conn.execute(
                    psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        psycopg.sql.Identifier(db_name)
                    )
                )


@pytest.fixture
def project(tmp_path: Path, test_db_url: str, maintenance_url: str) -> Iterator[Project]:
    """A project declaring ``widget``; every database it creates is dropped after the test."""
    if shutil.which("psql") is None:
        pytest.skip("test-db provision-template applies DDL through psql, which is not on PATH")
    schema = tmp_path / "db" / "schema"
    schema.mkdir(parents=True)
    (schema / "10_widget.sql").write_text(_WIDGET_DDL)
    environments = tmp_path / "db" / "environments"
    environments.mkdir(parents=True)
    (environments / "test.yaml").write_text(
        f"name: test\ninclude_dirs:\n  - db/schema\ndatabase_url: {test_db_url}\n"
    )
    proj = Project(
        root=tmp_path,
        url=test_db_url,
        maintenance_url=maintenance_url,
        prefix=f"confiture_tdbcli_{uuid.uuid4().hex[:8]}",
    )
    try:
        yield proj
    finally:
        proj.drop_created()


def _json(stdout: str) -> dict:
    """The payload, which must be all of stdout: a consumer parses the stream."""
    return json.loads(stdout)


def _provision(project: Project, template: str) -> str:
    """Provision *template* from the project's DDL by its command line; return its hash."""
    result = runner.invoke(
        app,
        [
            "test-db",
            "provision-template",
            "--template",
            template,
            "--env",
            "test",
            "--project-dir",
            str(project.root),
            "--database-url",
            project.url,
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    return _json(result.stdout)["stored_hash"]


def _clone(project: Project, template: str, target: str) -> None:
    result = runner.invoke(
        app,
        [
            "test-db",
            "clone",
            "--template",
            template,
            "--target",
            target,
            "--database-url",
            project.url,
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output


def _tablespace_location(project: Project, tablespace: str) -> str | None:
    """The LOCATION of *tablespace*, or None when it does not exist."""
    with psycopg.connect(project.maintenance_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT pg_tablespace_location(oid) FROM pg_tablespace WHERE spcname = %s",
            (tablespace,),
        ).fetchone()
    return row[0] if row else None


def _database_tablespace(project: Project, db_name: str) -> str | None:
    with psycopg.connect(project.maintenance_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT t.spcname FROM pg_database d "
            "JOIN pg_tablespace t ON d.dattablespace = t.oid WHERE d.datname = %s",
            (db_name,),
        ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_reports_the_template_and_clones_a_provision_created(project: Project) -> None:
    template = project.name("tmpl")
    first, second = project.name("clone_1"), project.name("clone_2")
    schema_hash = _provision(project, template)
    _clone(project, template, first)
    _clone(project, template, second)
    unmanaged = project.create_unmanaged("foreign")

    result = runner.invoke(
        app, ["test-db", "list", "--database-url", project.url, "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    mine = sorted(
        (db for db in _json(result.stdout)["databases"] if db["name"].startswith(project.prefix)),
        key=lambda db: db["name"],
    )
    assert mine == [
        {"name": first, "kind": "clone", "detail": template},
        {"name": second, "kind": "clone", "detail": template},
        {"name": template, "kind": "template", "detail": schema_hash},
    ]
    assert unmanaged in project.datnames()


def test_list_in_text_names_each_managed_database(project: Project) -> None:
    template = project.name("tmpl")
    clone = project.name("clone")
    _provision(project, template)
    _clone(project, template, clone)

    result = runner.invoke(app, ["test-db", "list", "--database-url", project.url])

    assert result.exit_code == 0, result.output
    assert template in result.stdout
    assert clone in result.stdout


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def _status(project: Project, template: str):
    return runner.invoke(
        app,
        [
            "test-db",
            "status",
            "--template",
            template,
            "--env",
            "test",
            "--project-dir",
            str(project.root),
            "--database-url",
            project.url,
            "--format",
            "json",
        ],
    )


def test_status_reports_a_freshly_provisioned_template_current(project: Project) -> None:
    template = project.name("tmpl")
    schema_hash = _provision(project, template)

    result = _status(project, template)

    assert result.exit_code == 0, result.output
    payload = _json(result.stdout)
    assert (payload["name"], payload["state"]) == (template, "current")
    assert payload["stored_hash"] == payload["current_hash"] == schema_hash


def test_status_reports_the_template_stale_once_the_ddl_changes(project: Project) -> None:
    template = project.name("tmpl")
    schema_hash = _provision(project, template)
    (project.root / "db" / "schema" / "20_gadget.sql").write_text(
        "CREATE TABLE gadget (id BIGINT PRIMARY KEY);\n"
    )

    result = _status(project, template)

    assert result.exit_code == FINDINGS, result.output
    payload = _json(result.stdout)
    assert payload["state"] == "stale"
    assert payload["stored_hash"] == schema_hash
    assert payload["current_hash"] != schema_hash


def test_status_reports_a_template_never_provisioned_absent(project: Project) -> None:
    template = project.name("tmpl")

    result = _status(project, template)

    assert result.exit_code == FINDINGS, result.output
    payload = _json(result.stdout)
    assert (payload["state"], payload["stored_hash"]) == ("absent", None)
    assert template not in project.datnames()


# ---------------------------------------------------------------------------
# drop
# ---------------------------------------------------------------------------


def test_drop_removes_the_clone_it_names_and_nothing_else(project: Project) -> None:
    template = project.name("tmpl")
    doomed, kept = project.name("clone_1"), project.name("clone_2")
    _provision(project, template)
    _clone(project, template, doomed)
    _clone(project, template, kept)

    result = runner.invoke(
        app,
        ["test-db", "drop", "--target", doomed, "--database-url", project.url, "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = _json(result.stdout)
    assert (payload["target"], payload["dropped"]) == (doomed, True)
    assert project.datnames() == {template, kept}


def test_drop_reports_a_database_that_does_not_exist(project: Project) -> None:
    missing = project.name("never_created")

    result = runner.invoke(
        app,
        ["test-db", "drop", "--target", missing, "--database-url", project.url, "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    assert _json(result.stdout)["dropped"] is False
    assert project.datnames() == set()


def test_drop_refuses_an_unmanaged_database_unless_forced(project: Project) -> None:
    foreign = project.create_unmanaged("foreign")

    refused = runner.invoke(
        app,
        ["test-db", "drop", "--target", foreign, "--database-url", project.url, "--format", "json"],
    )

    assert refused.exit_code == exit_code_of("CONFIG_010"), refused.output
    assert _json(refused.stdout)["error"]["code"] == "CONFIG_010"
    assert foreign in project.datnames()

    forced = runner.invoke(
        app,
        [
            "test-db",
            "drop",
            "--target",
            foreign,
            "--force",
            "--database-url",
            project.url,
            "--format",
            "json",
        ],
    )

    assert forced.exit_code == 0, forced.output
    assert _json(forced.stdout)["dropped"] is True
    assert foreign not in project.datnames()


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


def test_prune_drops_every_clone_of_its_template_and_keeps_the_rest(project: Project) -> None:
    pruned, other = project.name("tmpl_a"), project.name("tmpl_b")
    a1, a2, b1 = project.name("a_clone_1"), project.name("a_clone_2"), project.name("b_clone_1")
    _provision(project, pruned)
    _provision(project, other)
    _clone(project, pruned, a1)
    _clone(project, pruned, a2)
    _clone(project, other, b1)
    foreign = project.create_unmanaged("foreign")

    result = runner.invoke(
        app,
        [
            "test-db",
            "prune",
            "--template",
            pruned,
            "--database-url",
            project.url,
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json(result.stdout)
    assert payload["template"] == pruned
    assert sorted(payload["dropped"]) == [a1, a2]
    assert project.datnames() == {pruned, other, b1, foreign}

    again = runner.invoke(
        app,
        [
            "test-db",
            "prune",
            "--template",
            pruned,
            "--database-url",
            project.url,
            "--format",
            "json",
        ],
    )

    assert again.exit_code == 0, again.output
    assert _json(again.stdout)["dropped"] == []
    assert project.datnames() == {pruned, other, b1, foreign}


# ---------------------------------------------------------------------------
# ram-setup
# ---------------------------------------------------------------------------


@pytest.fixture
def shm_location(project: Project) -> Iterator[str]:
    """A ``/dev/shm`` path owned by this test; removed afterwards whoever created it."""
    if not _SHM.is_dir():
        pytest.skip("no /dev/shm tmpfs on this host")
    location = str(_SHM / project.prefix)
    try:
        yield location
    finally:
        shutil.rmtree(location, ignore_errors=True)


def test_ram_setup_refuses_a_location_outside_tmpfs(project: Project, tmp_path: Path) -> None:
    tablespace = f"{project.prefix}_ts"
    location = tmp_path / "not_tmpfs"

    result = runner.invoke(
        app,
        [
            "test-db",
            "ram-setup",
            "--tablespace",
            tablespace,
            "--location",
            str(location),
            "--database-url",
            project.url,
            "--format",
            "json",
        ],
    )

    assert result.exit_code == exit_code_of("CONFIG_010"), result.output
    assert _json(result.stdout)["error"]["code"] == "CONFIG_010"
    assert not location.exists()
    assert _tablespace_location(project, tablespace) is None


def _foreign_owner() -> str:
    """An OS user this process cannot hand a directory to, or skip when there is none."""
    if os.geteuid() == 0:
        pytest.skip("running as root: ram-setup prepares the directory itself, no guided path")
    for candidate in ("postgres", "root"):
        try:
            if pwd.getpwnam(candidate).pw_uid != os.geteuid():
                return candidate
        except KeyError:
            continue
    pytest.skip("no OS user other than this process's own to hand the directory to")


def test_ram_setup_prints_the_privileged_command_when_it_cannot_prepare_the_directory(
    project: Project, shm_location: str
) -> None:
    tablespace = f"{project.prefix}_ts"
    owner = _foreign_owner()

    result = runner.invoke(
        app,
        [
            "test-db",
            "ram-setup",
            "--tablespace",
            tablespace,
            "--location",
            shm_location,
            "--owner",
            owner,
            "--database-url",
            project.url,
            "--format",
            "json",
        ],
    )

    assert result.exit_code == _ACTION_REQUIRED, result.output
    payload = _json(result.stdout)
    assert payload["action_required"] is True
    assert payload["action_command"] == (
        f"sudo install -d -o {owner} -g {owner} -m 700 {shm_location}"
    )
    assert (payload["recreated"], payload["dropped_databases"]) == (False, [])
    assert _tablespace_location(project, tablespace) is None


@dataclass
class RamHost:
    tablespace: str
    location: str
    owner: str


def _server_os_user(project: Project) -> tuple[str, int] | None:
    """The OS user owning the server's data directory, when this host can see it."""
    with psycopg.connect(project.maintenance_url, autocommit=True) as conn:
        datadir = conn.execute("SHOW data_directory").fetchone()[0]
    try:
        uid = Path(datadir).stat().st_uid
        return pwd.getpwuid(uid).pw_name, uid
    except (OSError, KeyError):
        return None


@pytest.fixture
def ram_host(project: Project, shm_location: str) -> Iterator[RamHost]:
    """A tablespace name and ``/dev/shm`` LOCATION ``ram-setup`` can really create.

    Skips where the host cannot hold one, as ``tests/integration/conftest.py``'s
    tmpfs fixtures do: a tablespace needs a superuser connection, and its LOCATION
    must be handed to the server's OS user, which needs root or to be that user.
    """
    with psycopg.connect(project.maintenance_url, autocommit=True) as conn:
        superuser = conn.execute("SELECT current_setting('is_superuser')").fetchone()[0] == "on"
    if not superuser:
        pytest.skip("ram-setup creates a tablespace, which needs a superuser connection")
    server_user = _server_os_user(project)
    if server_user is None:
        pytest.skip(
            "cannot resolve the PostgreSQL server's OS user from its data directory "
            "(a remote server, or a data directory this process cannot stat)"
        )
    owner, uid = server_user
    if os.geteuid() not in (0, uid):
        pytest.skip(f"this process can hand a /dev/shm directory to {owner!r} only as root")
    tablespace = f"{project.prefix}_ts"
    try:
        yield RamHost(tablespace=tablespace, location=shm_location, owner=owner)
    finally:
        project.drop_created()
        with psycopg.connect(project.maintenance_url, autocommit=True) as conn:
            conn.execute(
                psycopg.sql.SQL("DROP TABLESPACE IF EXISTS {}").format(
                    psycopg.sql.Identifier(tablespace)
                )
            )


def _ram_setup(project: Project, host: RamHost):
    return runner.invoke(
        app,
        [
            "test-db",
            "ram-setup",
            "--tablespace",
            host.tablespace,
            "--location",
            host.location,
            "--owner",
            host.owner,
            "--database-url",
            project.url,
            "--format",
            "json",
        ],
    )


def test_ram_setup_creates_the_tablespace_then_resets_it_dropping_its_clone(
    project: Project, ram_host: RamHost
) -> None:
    created = _ram_setup(project, ram_host)

    assert created.exit_code == 0, created.output
    payload = _json(created.stdout)
    assert (payload["recreated"], payload["action_required"]) == (False, False)
    assert payload["dropped_databases"] == []
    assert _tablespace_location(project, ram_host.tablespace) == ram_host.location

    template, clone = project.name("tmpl"), project.name("ram_clone")
    _provision(project, template)
    TestDbProvisioner(project.url).clone(template, clone, tablespace=ram_host.tablespace)
    assert _database_tablespace(project, clone) == ram_host.tablespace

    reset = _ram_setup(project, ram_host)

    assert reset.exit_code == 0, reset.output
    payload = _json(reset.stdout)
    assert (payload["recreated"], payload["action_required"]) == (True, False)
    assert payload["dropped_databases"] == [clone]
    assert project.datnames() == {template}
    assert _tablespace_location(project, ram_host.tablespace) == ram_host.location
