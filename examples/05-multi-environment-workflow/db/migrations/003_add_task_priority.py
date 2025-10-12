"""Add priority column to tasks table

This migration adds a priority column to help users prioritize their work.

Migration: 003
Created: 2025-10-03
"""

from confiture.models.migration import Migration


class AddTaskPriority(Migration):
    """Add priority column to tasks table."""

    version = "003"
    name = "add_task_priority"
    description = "Add priority column to tasks table (low, medium, high, urgent)"

    def up(self) -> None:
        """Apply migration: Add priority column."""
        # Add column with default
        self.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'medium'
        """)

        # Add constraint
        self.execute("""
            ALTER TABLE tasks
            ADD CONSTRAINT tasks_priority_valid
            CHECK (priority IN ('low', 'medium', 'high', 'urgent'))
        """)

        # Create index for priority filtering
        self.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_priority
            ON tasks(priority)
        """)

        # Add comment
        self.execute("""
            COMMENT ON COLUMN tasks.priority IS 'Task priority: low, medium, high, or urgent'
        """)

    def down(self) -> None:
        """Rollback migration: Remove priority column."""
        # Drop index
        self.execute("""
            DROP INDEX IF EXISTS idx_tasks_priority
        """)

        # Drop constraint
        self.execute("""
            ALTER TABLE tasks
            DROP CONSTRAINT IF EXISTS tasks_priority_valid
        """)

        # Drop column
        self.execute("""
            ALTER TABLE tasks
            DROP COLUMN IF EXISTS priority
        """)
