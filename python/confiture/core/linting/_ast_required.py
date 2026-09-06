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

import sys

# Module-level guard so the skip notice fires once per process rather
# than once per migration (a CI run with many migrations would otherwise
# spam logs).  Reset between tests via monkeypatch.
_skip_warned: bool = False


def is_pglast_available() -> bool:
    """Always True: pglast is a dependency (D13).

    The ``not available`` branches it guards are deleted with the regex
    backends (Phase 05 Cycle 5).
    """
    return True


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
