"""Compatibility shim — removed at 1.0.0. Import from ``confiture.core.seed.validation.prep_seed.models`` instead.

Seed logic lives in one package since 0.53.0 (Phase 08); this module re-exports
its new home so existing imports keep working for one release.
"""

from confiture.core.seed.validation.prep_seed.models import *  # noqa: F401,F403
