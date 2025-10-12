"""Add bio column to users table

Migration: 001_add_user_bio
Author: Confiture Tutorial
Date: 2025-10-12

Description:
  Adds a bio TEXT column to the users table for user biographies.
  Column is nullable to allow existing users without bio.

Rollback:
  Safe - simply drops the bio column
"""

from confiture.models.migration import Migration


class AddUserBio(Migration):
    """Add bio column to users table."""

    version = "001"
    name = "add_user_bio"

    def up(self) -> None:
        """Apply migration: Add bio column."""
        self.execute("""
            ALTER TABLE users
            ADD COLUMN bio TEXT
        """)

        # Add column comment for documentation
        self.execute("""
            COMMENT ON COLUMN users.bio IS
            'User biography (supports markdown)'
        """)

    def down(self) -> None:
        """Rollback migration: Remove bio column."""
        self.execute("""
            ALTER TABLE users
            DROP COLUMN bio
        """)
