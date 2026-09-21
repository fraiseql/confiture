-- Migration: golden
-- Version: <version>

-- confiture:irreversible no rollback derived for ADD_TRIGGER users.trigger_users_updated_at

-- confiture:tier destructive
DROP FUNCTION IF EXISTS update_updated_at_column();

-- confiture:tier irreversible
DROP TABLE users;
