-- Migration: golden
-- Version: <version>

-- confiture:tier destructive
DROP TRIGGER IF EXISTS trigger_tb_user_updated_at ON tb_user;

-- confiture:tier destructive
DROP TRIGGER IF EXISTS trigger_tb_post_updated_at ON tb_post;

-- confiture:tier destructive
DROP TRIGGER IF EXISTS trigger_tb_comment_updated_at ON tb_comment;

-- confiture:tier destructive
DROP FUNCTION IF EXISTS update_updated_at_column();

DROP EXTENSION IF EXISTS uuid-ossp;

-- confiture:tier destructive
DROP EXTENSION IF EXISTS unaccent;

-- confiture:tier destructive
DROP EXTENSION IF EXISTS pg_trgm;

-- confiture:tier destructive
DROP EXTENSION IF EXISTS btree_gist;

-- confiture:tier irreversible
DROP TABLE tv_user;

-- confiture:tier irreversible
DROP TABLE tv_post;

-- confiture:tier irreversible
DROP TABLE tv_comment;

-- confiture:tier irreversible
DROP TABLE tb_user;

-- confiture:tier irreversible
DROP TABLE tb_post;

-- confiture:tier irreversible
DROP TABLE tb_comment;
