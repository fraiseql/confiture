"""Shared helpers for AST-only lint rules (issue #124).

Rules that need pairwise structural analysis (matching ``CREATE`` to a
later ``ALTER … OWNER TO`` of the same qualified name across realistic
PostgreSQL SQL with dollar-quoted strings, CHECK-constraint literals, and
multi-statement DO blocks) can't be reliably implemented with regex.
When pglast is not installed, those rules emit a single skip notice and
return no violations rather than ship a half-working detector — a
false-negative ownership lint is worse than no lint, because users trust
the green check.

Used by :class:`~confiture.core.linting.libraries.ownership.Own001OwnershipCoverage`
today; future AST-only rules import the same helpers.
"""

from __future__ import annotations

import importlib.util
import sys
from functools import cache

# Test seam: when True, :func:`is_pglast_available` reports unavailable
# regardless of what's installed.  Tests flip this via monkeypatch — the
# production path leaves it ``False`` and the ``importlib`` check decides.
_force_unavailable: bool = False

# Module-level guard so the skip notice fires once per process rather
# than once per migration (a CI run with many migrations would otherwise
# spam logs).  Reset between tests via monkeypatch.
_skip_warned: bool = False


@cache
def is_pglast_available() -> bool:
    """Return True when the ``pglast`` package is importable.

    Cached because ``importlib.util.find_spec`` walks ``sys.path`` on
    every call; the answer doesn't change at runtime in practice.  Tests
    that need to force a False reading can ``monkeypatch.setattr`` the
    module's ``_force_unavailable`` flag *and* clear this cache.
    """
    if _force_unavailable:
        return False
    return importlib.util.find_spec("pglast") is not None


def emit_skip_notice(message: str) -> None:
    """Write *message* to stderr exactly once per process.

    Subsequent calls within the same process are no-ops.
    """
    global _skip_warned
    if _skip_warned:
        return
    _skip_warned = True
    print(message, file=sys.stderr)


__all__ = ["emit_skip_notice", "is_pglast_available"]
