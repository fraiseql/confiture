"""Per-worker test-database name/URL resolution for pytest-xdist.

**This module's pure functions are the primary integration surface, not the
fixtures.** An xdist worker resolves its database name from
``PYTEST_XDIST_WORKER`` — but a fixture runs at *test* time, which is too late
for an application that freezes a ``Settings()`` / connection-pool singleton at
*module import*. The supported integration for such apps is to call
:func:`resolve_worker_db_url` from the consumer's ``conftest.py`` **at import
time**, before the app's settings are imported::

    # conftest.py — runs before the app package is imported
    import os
    from confiture.testing.worker_db import resolve_worker_db_url

    os.environ["DATABASE_URL"] = resolve_worker_db_url(os.environ["DATABASE_URL"])
    # only now import anything that reads DATABASE_URL into a frozen singleton

The :func:`confiture_worker_db` fixture (in ``pytest_plugin``) is convenience for
apps that read the URL lazily; it cannot retro-fix an already-frozen singleton.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

from confiture.core.temp_database import _replace_dbname

# A worker suffix this module appends, e.g. "_gw0". Stripped before re-appending
# so resolution is idempotent (never "_gw0_gw1").
_WORKER_SUFFIX_RE = re.compile(r"_gw\d+$")
_WORKER_ID_RE = re.compile(r"^gw\d+$")


def current_worker_id() -> str | None:
    """Return the active pytest-xdist worker id (``"gw0"``…), or None.

    Returns None for non-distributed runs and for the xdist controller
    (``"master"``), both of which map to the single base database.
    """
    worker = os.getenv("PYTEST_XDIST_WORKER")
    if not worker or worker == "master":
        return None
    return worker


def resolve_worker_db_name(base: str, *, worker_id: str | None = None) -> str:
    """Resolve the per-worker database name for *base*.

    ``gw0`` → ``{base}_gw0``; no/unknown worker (single-process or ``master``)
    → ``base``. Idempotent: an already-suffixed base is re-resolved cleanly
    rather than double-suffixed.

    Args:
        base: The base database name.
        worker_id: Explicit worker id; defaults to the live
            ``PYTEST_XDIST_WORKER``.

    Returns:
        The resolved database name.
    """
    wid = worker_id if worker_id is not None else current_worker_id()
    stripped = _WORKER_SUFFIX_RE.sub("", base)
    if not wid or not _WORKER_ID_RE.match(wid):
        return stripped
    return f"{stripped}_{wid}"


def resolve_worker_db_url(base_url: str, *, worker_id: str | None = None) -> str:
    """Resolve the per-worker connection URL for *base_url*.

    Replaces the database component of *base_url* with the worker-resolved name
    (see :func:`resolve_worker_db_name`). This is the import-time entry point
    consumers should call from ``conftest.py`` (see the module docstring).

    Args:
        base_url: The base connection URL.
        worker_id: Explicit worker id; defaults to the live
            ``PYTEST_XDIST_WORKER``.

    Returns:
        The URL with its database name resolved for this worker.
    """
    base_name = urlparse(base_url).path.lstrip("/")
    worker_name = resolve_worker_db_name(base_name, worker_id=worker_id)
    return _replace_dbname(base_url, worker_name)
