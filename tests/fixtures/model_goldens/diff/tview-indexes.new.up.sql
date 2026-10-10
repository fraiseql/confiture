-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS tb_author (
    pk_author BIGINT NOT NULL,
    id UUID NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (pk_author),
    UNIQUE (id)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS tb_post (
    pk_post BIGINT NOT NULL,
    id UUID NOT NULL,
    fk_author BIGINT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    PRIMARY KEY (pk_post),
    FOREIGN KEY (fk_author) REFERENCES tb_author,
    UNIQUE (id)
);

-- confiture:tier lock_risky
SELECT tviews.pg_tviews_create_or_replace('tv_author', $tview$SELECT a.pk_author, a.id, a.name, jsonb_build_object('id', a.id, 'name', a.name) AS data FROM tb_author AS a$tview$);
CREATE INDEX IF NOT EXISTS ix_tv_author_name ON tv_author (name);

-- confiture:tier lock_risky
SELECT tviews.pg_tviews_create_or_replace('tv_post', $tview$SELECT p.pk_post, p.id, p.title, p.body, jsonb_build_object('id', p.id, 'title', p.title, 'body', p.body) AS data FROM tb_post AS p$tview$);
CREATE INDEX IF NOT EXISTS ix_tv_post_body ON tv_post (body);
CREATE INDEX IF NOT EXISTS ix_tv_post_lookup ON tv_post (id, title);
