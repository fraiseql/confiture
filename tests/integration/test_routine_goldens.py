"""What the routine and view checks print about one tree, pinned from the CLI.

``migrate validate --check-signatures`` / ``--check-body`` / ``--check-body-views``
/ ``--check-body-replay`` / ``--require-migration-bodies`` and ``migrate
fix-signatures`` are read by deploy gates that key their alert state on the
strings these print — ``stale_signature``, ``source_signatures``, a body drift's
``schema.name`` and hashes. Each golden is the CLI's JSON and exit code for
``tests/fixtures/routine_drift`` on a database built from it (``clean``), on one
changed behind its back (``drift``), and between two commits of a repository
(``accompaniment``), so a change to what a reader of routines or views sees is
a visible edit to these files.

Recorded by ``scripts/refresh_model_goldens.py --write --only routines``; a
refresh names what moved, before and after, in ``CHANGELOG.md`` under
``## [Unreleased]``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlparse, urlunparse

import psycopg
from psycopg import sql
from test_diff_goldens import _explain, goldens


def _server_version(conn: psycopg.Connection) -> int:
    row = conn.execute("SHOW server_version_num").fetchone()
    assert row is not None
    return int(row[0])


def test_routine_goldens_are_recorded() -> None:
    assert goldens.recorded("routines"), (
        "tests/fixtures/model_goldens/routines/ is empty; record it with "
        "`uv run python scripts/refresh_model_goldens.py --write --only routines`"
    )


def test_every_command_is_recorded_for_every_scenario_and_generation() -> None:
    expected = {
        f"routines/{scenario}.{command}{suffix}"
        for scenario in goldens.ROUTINE_SCENARIOS
        for command in goldens.ROUTINE_COMMANDS
        for suffix in (
            (".pg15.json", ".pg16.json") if command in goldens.VIEW_DEPARSE_COMMANDS else (".json",)
        )
    }
    assert expected <= set(goldens.recorded("routines"))


def test_a_view_is_deparsed_by_generation(maintenance_connection: psycopg.Connection) -> None:
    """Why the view goldens are recorded twice: the deparse, measured on this server."""
    server = _server_version(maintenance_connection)
    maintenance_connection.execute(
        "CREATE OR REPLACE TEMP VIEW deparse_probe AS SELECT oid FROM pg_class"
    )
    deparsed = maintenance_connection.execute(
        "SELECT pg_get_viewdef('deparse_probe'::regclass)"
    ).fetchone()
    assert deparsed is not None
    qualified = "pg_class.oid" in str(deparsed[0])
    assert (goldens.deparse_generation(server), qualified) in {("pg15", True), ("pg16", False)}


def test_the_routine_checks_match_their_goldens(
    test_db_url: str, maintenance_connection: psycopg.Connection
) -> None:
    @contextmanager
    def fresh() -> Iterator[str]:
        name = f"confiture_golden_{uuid.uuid4().hex[:8]}"
        maintenance_connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            yield urlunparse(urlparse(test_db_url)._replace(path=f"/{name}"))
        finally:
            maintenance_connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )

    live = goldens.routine_goldens(fresh)
    server = _server_version(maintenance_connection)
    on_disk = goldens.of_generation(
        goldens.recorded("routines"), goldens.deparse_generation(server)
    )
    assert live == on_disk, (
        "a routine or view check printed something else. If deliberate, run "
        "`uv run python scripts/refresh_model_goldens.py --write --only routines` and "
        "name what moved, before and after, in CHANGELOG.md.\n" + _explain(live, on_disk)
    )
