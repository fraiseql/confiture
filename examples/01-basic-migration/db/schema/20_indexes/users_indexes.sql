-- Indexes for users table
-- Created after tables for performance

-- Email index for fast lookups and uniqueness
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Created date index for sorting (descending for recent-first)
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at DESC);

-- Display name index for search
CREATE INDEX IF NOT EXISTS idx_users_display_name ON users(display_name);
