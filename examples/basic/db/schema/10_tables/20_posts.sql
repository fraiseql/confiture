-- Posts table with modern identity trinity pattern
CREATE TABLE posts (
    -- Auto-incrementing internal ID
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- UUID for external APIs
    pk_post UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,

    -- Human-readable identifier (URL-friendly slug)
    slug TEXT NOT NULL UNIQUE,

    -- Foreign key (uses internal id for performance)
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Data fields
    title TEXT NOT NULL,
    content TEXT NOT NULL,

    -- Timestamps
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_posts_pk_post ON posts(pk_post);
CREATE INDEX idx_posts_slug ON posts(slug);
CREATE INDEX idx_posts_user_id ON posts(user_id);
CREATE INDEX idx_posts_published_at ON posts(published_at DESC) WHERE published_at IS NOT NULL;
CREATE INDEX idx_posts_created_at ON posts(created_at DESC);
