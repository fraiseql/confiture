"""The plugin's tests run inside confiture's repository, against its test database.

The database fixtures are confiture's own, so a DSN is routed, skipped or failed by
the one rule ``tests/conftest.py`` states. ``pyproject.toml`` puts the repository
root on the path for this import.
"""

from tests.conftest import test_db_connection, test_db_url

__all__ = ["test_db_connection", "test_db_url"]
