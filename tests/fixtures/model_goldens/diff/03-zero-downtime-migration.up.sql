-- Migration: golden
-- Version: <version>

-- confiture:destructive
-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS idx_users_full_name;

-- confiture:tier reversible
ALTER TABLE users RENAME COLUMN full_name TO first_name;

-- confiture:tier lock_risky
ALTER TABLE users ADD COLUMN last_name TEXT NOT NULL;

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_first_name ON users (first_name);

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_last_name ON users (last_name);

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_full_name ON users (first_name, last_name);
