-- Migration: golden
-- Version: <version>

DROP EXTENSION IF EXISTS uuid-ossp;

-- confiture:tier destructive
DROP EXTENSION IF EXISTS btree_gist;

-- confiture:tier irreversible
DROP TABLE users;
