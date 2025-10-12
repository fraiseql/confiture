-- Users table
-- Stores user accounts and profiles

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    bio TEXT,  -- Added via migration 001_add_user_bio
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table and column comments for documentation
COMMENT ON TABLE users IS 'User accounts and profiles';
COMMENT ON COLUMN users.id IS 'Unique user identifier (UUID v4)';
COMMENT ON COLUMN users.email IS 'User email address (unique)';
COMMENT ON COLUMN users.display_name IS 'Public display name';
COMMENT ON COLUMN users.bio IS 'User biography (supports markdown)';
COMMENT ON COLUMN users.created_at IS 'Account creation timestamp';
COMMENT ON COLUMN users.updated_at IS 'Last profile update timestamp';
