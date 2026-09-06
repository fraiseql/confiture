-- Users table
-- Stores user accounts and profiles

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    bio TEXT,  -- Added via migration 001_add_user_bio
    avatar_url TEXT,  -- Added via migration 004_add_user_avatar
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT users_email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
    CONSTRAINT users_display_name_length CHECK (char_length(display_name) >= 2),
    CONSTRAINT users_bio_length CHECK (char_length(bio) <= 1000)
);

-- Table and column comments for documentation
COMMENT ON TABLE users IS 'User accounts and profiles';
COMMENT ON COLUMN users.id IS 'Unique user identifier (UUID v4)';
COMMENT ON COLUMN users.email IS 'User email address (unique, validated format)';
COMMENT ON COLUMN users.display_name IS 'Public display name (minimum 2 characters)';
COMMENT ON COLUMN users.bio IS 'User biography (supports markdown, max 1000 chars)';
COMMENT ON COLUMN users.avatar_url IS 'User avatar image URL (absolute URL)';
COMMENT ON COLUMN users.created_at IS 'Account creation timestamp';
COMMENT ON COLUMN users.updated_at IS 'Last profile update timestamp';

-- Auto-update updated_at trigger (defined in 40_functions/triggers.sql)
