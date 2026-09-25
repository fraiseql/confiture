-- Migration: golden
-- Version: <version>

-- confiture:tier destructive
DROP TRIGGER IF EXISTS trigger_users_updated_at ON users;

-- confiture:tier destructive
DROP FUNCTION IF EXISTS update_updated_at_column();

-- confiture:tier irreversible
DROP TABLE users;
