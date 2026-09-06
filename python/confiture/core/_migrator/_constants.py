"""Shared constants for the ``_migrator`` package.

Pure data extracted from ``engine.py`` so the concern
modules (engine / apply / baseline) can share one copy without a runtime
import cycle.  The tracking-table name rule lives in
:mod:`confiture.core.ledger`, next to the probe that resolves the name.
"""

from __future__ import annotations

import re

# Matches the psycopg error raised when an ALTER would rename a view column,
# used to attach a dependent-views resolution hint to the migration failure.
_VIEW_COLUMN_RENAME_RE = re.compile(r"cannot change name of view column", re.IGNORECASE)
