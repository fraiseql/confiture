"""Migration: test_from_cli

Version: 001
"""

from confiture.models.migration import Migration


class TestFromCli(Migration):
    """Migration: test_from_cli."""

    version = "001"
    name = "test_from_cli"

    def up(self) -> None:
        """Apply migration."""
        # TODO: Add your SQL statements here
        # Example:
        # self.execute("CREATE TABLE users (id SERIAL PRIMARY KEY)")
        pass

    def down(self) -> None:
        """Rollback migration."""
        # TODO: Add your rollback SQL statements here
        # Example:
        # self.execute("DROP TABLE users")
        pass
