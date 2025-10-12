"""Add status column to projects table

This migration adds a status column to track project lifecycle.

Migration: 002
Created: 2025-10-02
"""

from confiture.models.migration import Migration


class AddProjectStatus(Migration):
    """Add status column to projects table."""

    version = "002"
    name = "add_project_status"
    description = "Add status column to projects table (active, archived, deleted)"

    def up(self) -> None:
        """Apply migration: Add status column."""
        # Add column with default
        self.execute("""
            ALTER TABLE projects
            ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'
        """)

        # Add constraint
        self.execute("""
            ALTER TABLE projects
            ADD CONSTRAINT projects_status_valid
            CHECK (status IN ('active', 'archived', 'deleted'))
        """)

        # Create index for status filtering (partial index excludes deleted)
        self.execute("""
            CREATE INDEX IF NOT EXISTS idx_projects_status
            ON projects(status)
            WHERE status != 'deleted'
        """)

        # Add comment
        self.execute("""
            COMMENT ON COLUMN projects.status IS 'Project status: active, archived, or deleted'
        """)

    def down(self) -> None:
        """Rollback migration: Remove status column."""
        # Drop index
        self.execute("""
            DROP INDEX IF EXISTS idx_projects_status
        """)

        # Drop constraint
        self.execute("""
            ALTER TABLE projects
            DROP CONSTRAINT IF EXISTS projects_status_valid
        """)

        # Drop column
        self.execute("""
            ALTER TABLE projects
            DROP COLUMN IF EXISTS status
        """)
