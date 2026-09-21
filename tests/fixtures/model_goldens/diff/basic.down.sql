-- Migration: golden
-- Version: <version>

-- confiture:irreversible no rollback derived for ADD_EXTENSION uuid-ossp

-- confiture:tier irreversible
DROP TABLE users;

-- confiture:tier irreversible
DROP TABLE posts;

-- confiture:tier irreversible
DROP TABLE comments;
