"""The view helpers are installed only by ``confiture install-helpers``.

``migrate up`` installed them by default (``migration.view_helpers: auto``, #97); the
setting is gone. The view column rename regex still names PostgreSQL's refusal.
"""

import pytest
from pydantic import ValidationError

from confiture.config.environment import MigrationConfig
from confiture.core._migrator._constants import _VIEW_COLUMN_RENAME_RE


class TestViewHelpersAreNeverAConfigSetting:
    def test_the_setting_is_gone(self):
        """``migrate up`` installs nothing: ``view_helpers`` is no longer a key of the block."""
        with pytest.raises(ValidationError, match="view_helpers"):
            MigrationConfig.model_validate({"view_helpers": "auto"})


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
