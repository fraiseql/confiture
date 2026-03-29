"""Unit tests for view_helpers default change (Issue #97).

Verifies that:
1. MigrationConfig defaults to view_helpers='auto'
2. Invalid values are rejected by Literal validation
3. The view column rename regex matches PostgreSQL error messages
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from confiture.config.environment import MigrationConfig
from confiture.core._migrator.engine import _VIEW_COLUMN_RENAME_RE


class TestViewHelpersDefault:
    def test_default_is_auto(self):
        """MigrationConfig.view_helpers defaults to 'auto'."""
        config = MigrationConfig()
        assert config.view_helpers == "auto"

    def test_explicit_manual(self):
        """Explicit 'manual' overrides the default."""
        config = MigrationConfig(view_helpers="manual")
        assert config.view_helpers == "manual"

    def test_explicit_off(self):
        """Explicit 'off' overrides the default."""
        config = MigrationConfig(view_helpers="off")
        assert config.view_helpers == "off"

    def test_invalid_value_rejected(self):
        """Typos and invalid values are rejected with a validation error."""
        with pytest.raises(ValidationError, match="view_helpers"):
            MigrationConfig(view_helpers="auot")

    def test_invalid_value_none_rejected(self):
        """None is rejected."""
        with pytest.raises(ValidationError, match="view_helpers"):
            MigrationConfig(view_helpers=None)


class TestViewColumnRenameRegex:
    def test_matches_pg_error(self):
        """Regex matches the standard PostgreSQL error message."""
        msg = 'cannot change name of view column "allocation_id" to "id"'
        assert _VIEW_COLUMN_RENAME_RE.search(msg)

    def test_matches_with_hint(self):
        """Regex matches when the HINT line is appended."""
        msg = (
            'cannot change name of view column "old_col" to "new_col"\n'
            "HINT: Use ALTER VIEW ... RENAME COLUMN ..."
        )
        assert _VIEW_COLUMN_RENAME_RE.search(msg)

    def test_no_match_unrelated_error(self):
        """Regex does not match unrelated PostgreSQL errors."""
        msg = 'relation "users" does not exist'
        assert not _VIEW_COLUMN_RENAME_RE.search(msg)
