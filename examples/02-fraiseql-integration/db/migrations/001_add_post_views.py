"""Add view_count to posts

This migration adds view tracking to blog posts.

It is the Medium 2 half of this example: `db/schema/10_tables/generated.sql`
already declares `view_count`, because that file is the source of truth and a
fresh build gets the column for free. This migration is what an *existing*
database needs to reach the same shape, which is why every statement is
idempotent — applying it to a database built from current DDL is a no-op.
"""

from confiture.models.migration import Migration


class AddPostViews(Migration):
    """Add view_count to posts."""

    version = "001"
    name = "add_post_views"

    def up(self) -> None:
        """Apply migration: Add view_count column."""
        self.execute("""
            ALTER TABLE tb_post
            ADD COLUMN IF NOT EXISTS view_count INTEGER DEFAULT 0
        """)

        # Create index for sorting by popularity
        self.execute("""
            CREATE INDEX IF NOT EXISTS idx_tb_post_views
            ON tb_post(view_count DESC)
        """)

    def down(self) -> None:
        """Rollback migration: Remove view_count."""
        self.execute("""
            DROP INDEX IF EXISTS idx_tb_post_views
        """)

        self.execute("""
            ALTER TABLE tb_post
            DROP COLUMN IF EXISTS view_count
        """)
