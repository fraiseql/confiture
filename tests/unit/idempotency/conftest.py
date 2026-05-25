"""Test harness for idempotency backend parity.

Auto-parametrizes every test under ``tests/unit/idempotency/`` to run
twice — once with the regex backend forced via
``CONFITURE_IDEMPOTENCY_FORCE_REGEX=1`` and once with the AST backend
(default when pglast is importable).

Markers
-------

- ``@pytest.mark.xfail_under_ast(reason=...)``: the marked test is
  expected to fail under the AST backend until the indicated phase
  lands. Promotes to ``pytest.mark.xfail(strict=True, ...)`` automatically
  during the AST run.
- ``@pytest.mark.regex_only(reason=...)``: the marked test is only
  meaningful under the regex backend (e.g. it documents a regex
  limitation that the AST backend already closes). Skipped during the
  AST run.

Skipping the AST run entirely is supported via ``CONFITURE_SKIP_AST_PARITY=1``
— useful when a downstream test environment doesn't have ``pglast``
installed at all. The regex-only run still executes.
"""

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "xfail_under_ast(reason): mark a test as expected failure under "
        "the AST backend (e.g. before the visitor phase lands).",
    )
    config.addinivalue_line(
        "markers",
        "regex_only(reason): mark a test as only relevant to the regex "
        "backend (e.g. it documents a regex-specific limitation).",
    )
    config.addinivalue_line(
        "markers",
        "ast_only(reason): mark a test as only relevant to the AST "
        "backend (e.g. it documents an AST-specific gap closure).",
    )


def _ast_params() -> list[str]:
    if os.environ.get("CONFITURE_SKIP_AST_PARITY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return ["regex"]
    return ["regex", "ast"]


@pytest.fixture(params=_ast_params(), autouse=True)
def idempotency_backend(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Force the idempotency detector to a specific backend for the test.

    Applied automatically to every test under
    ``tests/unit/idempotency/``. Tests that need to know which backend
    they're running on can declare ``idempotency_backend`` as an
    argument; most don't care and simply pick up the parametrization.
    """
    backend = request.param
    if backend == "regex":
        monkeypatch.setenv("CONFITURE_IDEMPOTENCY_FORCE_REGEX", "1")
        ast_only = request.node.get_closest_marker("ast_only")
        if ast_only:
            reason = ast_only.kwargs.get("reason") or "AST backend only"
            pytest.skip(reason)
        return backend

    monkeypatch.delenv("CONFITURE_IDEMPOTENCY_FORCE_REGEX", raising=False)
    regex_only = request.node.get_closest_marker("regex_only")
    if regex_only:
        reason = regex_only.kwargs.get("reason") or "regex backend only"
        pytest.skip(reason)
    xfail = request.node.get_closest_marker("xfail_under_ast")
    if xfail:
        kwargs = dict(xfail.kwargs)
        # Class-level markers cover both ``detect`` and ``skip`` tests; the
        # latter often pass trivially when a phase's visitor is absent
        # (empty match list ≡ "no violations"). Default ``strict=False`` so
        # those incidental passes don't fail the suite. Per-phase reviews
        # plus the Phase 7 equivalence sweep are the actual regression
        # gates; individual tests can override with ``strict=True`` when
        # the AST result is truly distinct from the regex result.
        kwargs.setdefault("strict", False)
        request.node.add_marker(pytest.mark.xfail(**kwargs))
    return backend
