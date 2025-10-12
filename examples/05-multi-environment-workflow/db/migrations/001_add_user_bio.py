"""Add bio column to users table

This migration adds a bio TEXT column for user biographies.

Migration: 001
Created: 2025-10-01
"""

from confiture.models.migration import Migration


class AddUserBio(Migration):
    """Add bio column to users table."""

    version = "001"
    name = "add_user_bio"
    description = "Add bio column to users table for user biographies"

    def up(self) -> None:
        """Apply migration: Add bio column."""
        self.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS bio TEXT
        """)

        # Add constraint
        self.execute("""
            ALTER TABLE users
            ADD CONSTRAINT users_bio_length
            CHECK (char_length(bio) <= 1000)
        """)

        # Add comment
        self.execute("""
            COMMENT ON COLUMN users.bio IS 'User biography (supports markdown, max 1000 chars)'
        """)

    def down(self) -> None:
        """Rollback migration: Remove bio column."""
        # Drop constraint first
        self.execute("""
            ALTER TABLE users
            DROP CONSTRAINT IF EXISTS users_bio_length
        """)

        # Drop column
        self.execute("""
            ALTER TABLE users
            DROP COLUMN IF EXISTS bio
        """)
