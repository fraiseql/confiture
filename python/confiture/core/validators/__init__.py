"""Compatibility shim — removed at 1.0.0. Import from ``confiture.core.validation.comment_validator`` instead.

The module moved to its one home in 0.53.0 (Phase 08); this path re-exports it
so existing imports keep working for one release.
"""

from confiture.core.validation.comment_validator import *  # noqa: F403
