-- Migration: golden
-- Version: <version>

DROP EXTENSION IF EXISTS uuid-ossp;

-- confiture:tier irreversible
DROP TABLE users;

-- confiture:tier irreversible
DROP TABLE posts;

-- confiture:tier irreversible
DROP TABLE comments;
