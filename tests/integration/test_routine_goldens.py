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


def test_routine_goldens_are_recorded() -> None:
    assert goldens.recorded("routines"), (
        "tests/fixtures/model_goldens/routines/ is empty; record it with "
        "`uv run python scripts/refresh_model_goldens.py --write --only routines`"
    )


def test_every_command_is_recorded_for_every_scenario() -> None:
    expected = {
        f"routines/{scenario}.{command}.json"
        for scenario in goldens.ROUTINE_SCENARIOS
        for command in goldens.ROUTINE_COMMANDS
    }
    assert expected <= set(goldens.recorded("routines"))


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
    on_disk = goldens.recorded("routines")
    assert live == on_disk, (
        "a routine or view check printed something else. If deliberate, run "
        "`uv run python scripts/refresh_model_goldens.py --write --only routines` and "
        "name what moved, before and after, in CHANGELOG.md.\n" + _explain(live, on_disk)
    )
