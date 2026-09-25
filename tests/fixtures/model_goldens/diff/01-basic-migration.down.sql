-- Migration: golden
-- Version: <version>

-- confiture:tier irreversible
DROP TABLE users;

-- confiture:tier destructive
DROP EXTENSION IF EXISTS "uuid-ossp";

-- confiture:tier destructive
DROP EXTENSION IF EXISTS btree_gist;
