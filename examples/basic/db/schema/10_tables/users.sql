-- Users table with modern identity trinity pattern
CREATE TABLE users (
    -- Auto-incrementing internal ID (for joins, foreign keys)
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- UUID for external APIs (stable, non-sequential)
    pk_user UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,

    -- Human-readable identifier (for URLs, debugging)
    slug TEXT NOT NULL UNIQUE,

    -- Data fields
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    bio TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_users_pk_user ON users(pk_user);
CREATE INDEX idx_users_slug ON users(slug);
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_created_at ON users(created_at DESC);
