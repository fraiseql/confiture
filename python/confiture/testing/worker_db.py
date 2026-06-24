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
from collections.abc import Mapping
from urllib.parse import urlparse

from confiture.core.temp_database import _replace_dbname

# A worker suffix this module appends, e.g. "_gw0". Stripped before re-appending
# so resolution is idempotent (never "_gw0_gw1").
_WORKER_SUFFIX_RE = re.compile(r"_gw\d+$")
_WORKER_ID_RE = re.compile(r"^gw\d+$")

# Environment variables that signal a CI / automation context. This tuple is the
# single source of truth for the CI var-set: ``core/progress.py`` composes its
# TTY check on top of :func:`is_ci` rather than maintaining a second, drifting
# list (the eternal-sunshine anti-duplication rule).
_CI_ENV_VARS = (
    "CI",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "CIRCLECI",
    "BUILD_ID",
    "BUILD_NUMBER",
    "RUN_ID",
    "TRAVIS",
    "JENKINS_URL",
    "BUILDKITE",
    "DAGGER_SESSION_PORT",  # set by `dagger run` — the repo's local CI gate
)

# Values that mean an explicitly-disabled CI variable (e.g. ``CI=false``).
_CI_FALSEY = frozenset({"", "0", "false", "no", "off"})

# Env override for the clone-concurrency cap (#166). A valid int: >= 1 caps
# concurrent clones to that many; <= 0 forces unbounded. Unset or unparseable →
# auto (throttle only on an fsync=on cluster).
_MAX_CLONE_CONCURRENCY_VAR = "CONFITURE_TEST_MAX_CLONE_CONCURRENCY"

# Auto cap applied when the cluster has fsync=on and no override is set. Small
# enough to stop the WAL/checkpoint pile-up, large enough to keep some overlap.
_DEFAULT_FSYNC_ON_CLONE_CAP = 2


def is_ci() -> bool:
    """Return True when running under a CI / automation environment.

    Detects the common CI signals (``CI``, ``GITHUB_ACTIONS``, ``GITLAB_CI``,
    ``BUILDKITE``, Dagger, …). A variable counts only when present **and** not
    explicitly false-y — ``CI=false`` is not CI. Pure over ``os.environ`` with no
    TTY check (that belongs to progress-bar suppression, a deliberately different
    predicate; see :func:`confiture.core.progress._is_ci_environment`).

    This is advisory: it informs documented defaults (CI → pre-provisioned
    template + on-disk clones; local → RAM clones) and lets a consumer's conftest
    choose ``--from-artifact``. It is not branching logic inside the fixtures.
    """
    return any(os.environ.get(var, "").strip().lower() not in _CI_FALSEY for var in _CI_ENV_VARS)


def resolve_clone_concurrency(
    *, fsync_on: bool, env: Mapping[str, str] | None = None
) -> int | None:
    """Resolve the cap on concurrent clones for the worker-db fixture (#166).

    ``CONFITURE_TEST_MAX_CLONE_CONCURRENCY`` wins when set to a valid int: ``>= 1``
    caps concurrent clones to that many, ``<= 0`` forces unbounded. When it is unset
    or unparseable, the cap is chosen automatically: throttle to a small default
    only when *fsync_on* — concurrent ``CREATE DATABASE`` calls thrash WAL/checkpoint
    on an ``fsync=on`` cluster — and stay unbounded otherwise (typical CI runs
    ``fsync=off``, where concurrent clones are cheap).

    Args:
        fsync_on: Whether the target cluster runs with ``fsync = on`` (see
            :meth:`confiture.core.test_db.TestDbProvisioner.cluster_fsync_on`).
        env: Environment mapping to read (defaults to ``os.environ``).

    Returns:
        The cap to pass as ``clone(max_concurrency=...)``: a positive int, or
        ``None`` for unbounded.
    """
    environ = env if env is not None else os.environ
    raw = environ.get(_MAX_CLONE_CONCURRENCY_VAR, "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = None
        if value is not None:
            return value if value >= 1 else None
    return _DEFAULT_FSYNC_ON_CLONE_CAP if fsync_on else None


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
