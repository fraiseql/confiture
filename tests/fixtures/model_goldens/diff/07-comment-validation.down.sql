-- Migration: golden
-- Version: <version>

-- confiture:tier destructive
DROP VIEW IF EXISTS v_user_stats;

-- confiture:tier destructive
DROP VIEW IF EXISTS v_recent_posts;

-- confiture:tier irreversible
DROP TABLE posts;

-- confiture:tier irreversible
DROP TABLE users;
