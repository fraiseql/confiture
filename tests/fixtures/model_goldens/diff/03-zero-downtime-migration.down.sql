-- Migration: golden
-- Version: <version>

-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS idx_users_full_name;

-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS idx_users_last_name;

-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS idx_users_first_name;

-- confiture:tier irreversible
ALTER TABLE users DROP COLUMN last_name;

-- confiture:tier reversible
ALTER TABLE users RENAME COLUMN first_name TO full_name;

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_full_name ON users (full_name);
