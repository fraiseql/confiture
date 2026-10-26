-- Migration: golden
-- Version: <version>

-- confiture:creates tb_author
-- confiture:tier additive
CREATE TABLE tb_author (
    pk_author BIGINT NOT NULL,
    id UUID NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (pk_author),
    UNIQUE (id)
);

-- confiture:creates tb_post
-- confiture:tier additive
CREATE TABLE tb_post (
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
SELECT tviews.pg_tviews_create_or_replace('tv_post', $tview$SELECT p.pk_post, p.id, p.title, jsonb_build_object('id', p.id, 'title', p.title) AS data FROM tb_post AS p$tview$);
CREATE INDEX IF NOT EXISTS ix_tv_post_title ON tv_post (title);
CREATE INDEX IF NOT EXISTS ix_tv_post_lookup ON tv_post (title);
