-- Migration: golden
-- Version: <version>

-- confiture:destructive
-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS ix_tv_post_title;

-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS ix_tv_post_lookup;

-- confiture:tier lock_risky
SELECT tviews.pg_tviews_create_or_replace('tv_author', $tview$SELECT a.pk_author, a.id, a.name, jsonb_build_object('id', a.id, 'name', a.name) AS data FROM tb_author AS a$tview$);
CREATE INDEX IF NOT EXISTS ix_tv_author_name ON tv_author (name);

-- confiture:tier lock_risky
SELECT tviews.pg_tviews_create_or_replace('tv_post', $tview$SELECT p.pk_post, p.id, p.title, p.body, jsonb_build_object('id', p.id, 'title', p.title, 'body', p.body) AS data FROM tb_post AS p$tview$);

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tv_post_body ON tv_post (body);

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tv_post_lookup ON tv_post (id, title);
