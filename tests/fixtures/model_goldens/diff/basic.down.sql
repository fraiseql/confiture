-- Migration: golden
-- Version: <version>

-- confiture:tier irreversible
DROP TABLE comments;

-- confiture:tier irreversible
DROP TABLE posts;

-- confiture:tier irreversible
DROP TABLE users;

-- confiture:tier destructive
DROP EXTENSION IF EXISTS "uuid-ossp";
