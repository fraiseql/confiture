"""``confiture drift`` against a database built from each tree says what it said at ``6f94788b``.

A database applied verbatim from a tree has, by construction, no drift from that
tree. Whatever these goldens record beyond that is a defect in the comparison,
recorded rather than hidden: the campaign that makes drift compare one model to
itself is the fix, and the fix is visible as an edit to these files.

Recorded by ``scripts/refresh_model_goldens.py``; refreshed with ``--write`` and a
reason in ``CHANGELOG.md`` under ``## [Unreleased]``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlparse, urlunparse

import psycopg
from psycopg import sql
from test_diff_goldens import _explain, goldens


def test_drift_goldens_are_recorded() -> None:
    assert goldens.recorded("drift"), (
        "tests/fixtures/model_goldens/drift/ is empty; record it with "
        "`uv run python scripts/refresh_model_goldens.py --write --only drift`"
    )


def test_drift_matches_its_goldens(
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

    live = goldens.drift_goldens(fresh)
    on_disk = goldens.recorded("drift")
    assert live == on_disk, (
        "`confiture drift` output changed. If deliberate, run "
        "`uv run python scripts/refresh_model_goldens.py --write --only drift` and name "
        "the reason in CHANGELOG.md.\n" + _explain(live, on_disk)
    )
