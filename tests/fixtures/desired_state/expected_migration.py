"""Migration: init_from_spec

Version: 20260101000000
"""

from confiture.models.migration import Migration


class InitFromSpec(Migration):
    """Migration: init_from_spec."""

    version = "20260101000000"
    name = "init_from_spec"

    def up(self) -> None:
        """Apply migration."""
        self.execute("""CREATE TABLE IF NOT EXISTS tb_post (
    id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    score DOUBLE PRECISION
);""")
        self.execute("""CREATE TABLE IF NOT EXISTS tb_user (
    id INTEGER NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT,
    is_active BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);""")

    def down(self) -> None:
        """Rollback migration."""
        self.execute("DROP TABLE tb_user")
        self.execute("DROP TABLE tb_post")
