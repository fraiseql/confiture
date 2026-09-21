-- Migration: golden
-- Version: <version>

-- confiture:irreversible no rollback derived for ADD_TRIGGER tb_user.trigger_tb_user_updated_at

-- confiture:irreversible no rollback derived for ADD_TRIGGER tb_post.trigger_tb_post_updated_at

-- confiture:irreversible no rollback derived for ADD_TRIGGER tb_comment.trigger_tb_comment_updated_at

-- confiture:tier destructive
DROP FUNCTION IF EXISTS update_updated_at_column();

-- confiture:irreversible no rollback derived for ADD_EXTENSION uuid-ossp

-- confiture:irreversible no rollback derived for ADD_EXTENSION unaccent

-- confiture:irreversible no rollback derived for ADD_EXTENSION pg_trgm

-- confiture:irreversible no rollback derived for ADD_EXTENSION btree_gist

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
