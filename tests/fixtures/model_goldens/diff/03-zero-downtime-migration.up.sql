-- Migration: golden
-- Version: <version>

-- confiture:destructive
-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS idx_users_full_name;

-- confiture:tier reversible
ALTER TABLE users RENAME COLUMN full_name TO first_name;

-- confiture:tier lock_risky
ALTER TABLE users ADD COLUMN last_name TEXT;
-- confiture:backfill users.last_name
-- Replace this block with the statements that fix the rows of users where last_name is NULL,
-- or with `-- confiture:backfill none` when no row needs it: migrate up refuses this file until then.
ALTER TABLE users ADD CONSTRAINT users_last_name_not_null_check CHECK (last_name IS NOT NULL) NOT VALID;
ALTER TABLE users VALIDATE CONSTRAINT users_last_name_not_null_check;
ALTER TABLE users ALTER COLUMN last_name SET NOT NULL;
ALTER TABLE users DROP CONSTRAINT users_last_name_not_null_check;

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_first_name ON users (first_name);

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_last_name ON users (last_name);

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_full_name ON users (first_name, last_name);
