"""Migration: create_initial_schema

Version: 001

Creates the initial blog application schema with modern identity trinity pattern:
- id: Auto-incrementing BIGINT (internal use, foreign keys)
- pk_*: UUID (external APIs, stable identifiers)
- slug: Human-readable (URLs, debugging)
"""

from confiture.models.migration import Migration


class CreateInitialSchema(Migration):
    """Migration: create_initial_schema."""

    version = "001"
    name = "create_initial_schema"

    def up(self) -> None:
        """Apply migration."""
        # Enable UUID extension
        self.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

        # Create users table with identity trinity
        self.execute("""
            CREATE TABLE users (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                pk_user UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
                slug TEXT NOT NULL UNIQUE,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                bio TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Create posts table with identity trinity
        self.execute("""
            CREATE TABLE posts (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                pk_post UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
                slug TEXT NOT NULL UNIQUE,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                published_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Create comments table with identity trinity
        self.execute("""
            CREATE TABLE comments (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                pk_comment UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
                post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Create indexes for users
        self.execute("CREATE INDEX idx_users_pk_user ON users(pk_user)")
        self.execute("CREATE INDEX idx_users_slug ON users(slug)")
        self.execute("CREATE INDEX idx_users_username ON users(username)")
        self.execute("CREATE INDEX idx_users_email ON users(email)")
        self.execute("CREATE INDEX idx_users_created_at ON users(created_at DESC)")

        # Create indexes for posts
        self.execute("CREATE INDEX idx_posts_pk_post ON posts(pk_post)")
        self.execute("CREATE INDEX idx_posts_slug ON posts(slug)")
        self.execute("CREATE INDEX idx_posts_user_id ON posts(user_id)")
        self.execute(
            "CREATE INDEX idx_posts_published_at ON posts(published_at DESC) WHERE published_at IS NOT NULL"
        )
        self.execute("CREATE INDEX idx_posts_created_at ON posts(created_at DESC)")

        # Create indexes for comments
        self.execute("CREATE INDEX idx_comments_pk_comment ON comments(pk_comment)")
        self.execute("CREATE INDEX idx_comments_post_id ON comments(post_id)")
        self.execute("CREATE INDEX idx_comments_user_id ON comments(user_id)")
        self.execute("CREATE INDEX idx_comments_created_at ON comments(created_at DESC)")

    def down(self) -> None:
        """Rollback migration."""
        # Drop tables in reverse order (respect foreign keys)
        self.execute("DROP TABLE IF EXISTS comments CASCADE")
        self.execute("DROP TABLE IF EXISTS posts CASCADE")
        self.execute("DROP TABLE IF EXISTS users CASCADE")

        # Drop extension (optional - may be used by other tables)
        # self.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
