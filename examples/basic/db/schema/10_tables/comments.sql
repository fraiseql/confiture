-- Comments table with modern identity trinity pattern
CREATE TABLE comments (
    -- Auto-incrementing internal ID
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- UUID for external APIs
    pk_comment UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,

    -- Foreign keys (use internal ids for performance)
    post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Data fields
    content TEXT NOT NULL,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_comments_pk_comment ON comments(pk_comment);
CREATE INDEX idx_comments_post_id ON comments(post_id);
CREATE INDEX idx_comments_user_id ON comments(user_id);
CREATE INDEX idx_comments_created_at ON comments(created_at DESC);
