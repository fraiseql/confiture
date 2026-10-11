-- Migration: golden
-- Version: <version>

-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS ix_tv_post_lookup;

-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS ix_tv_post_body;

-- confiture:tier lock_risky
SELECT tviews.pg_tviews_create_or_replace('tv_post', $tview$SELECT p.pk_post, p.id, p.title, jsonb_build_object('id', p.id, 'title', p.title) AS data FROM tb_post AS p$tview$);

-- confiture:tier destructive
SELECT tviews.pg_tviews_drop('tv_author', if_exists => true);

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tv_post_lookup ON tv_post (title);

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tv_post_title ON tv_post (title);
