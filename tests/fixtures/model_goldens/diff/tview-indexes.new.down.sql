-- Migration: golden
-- Version: <version>

-- confiture:tier destructive
SELECT tviews.pg_tviews_drop('tv_post', if_exists => true);

-- confiture:tier destructive
SELECT tviews.pg_tviews_drop('tv_author', if_exists => true);

-- confiture:tier irreversible
DROP TABLE tb_post;

-- confiture:tier irreversible
DROP TABLE tb_author;
