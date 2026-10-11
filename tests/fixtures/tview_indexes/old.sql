-- A pg_tviews TVIEW's indexes, compared as a table's are: the pair's diff adds a
-- TVIEW with its index, redefines one with a new column and an index on it,
-- drops an index, and rebuilds one whose keys change.
CREATE TABLE tb_author (
    pk_author BIGINT PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    name TEXT NOT NULL
);

CREATE TABLE tb_post (
    pk_post BIGINT PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    fk_author BIGINT NOT NULL REFERENCES tb_author,
    title TEXT NOT NULL,
    body TEXT
);

CREATE TABLE tv_post AS
SELECT p.pk_post, p.id, p.title, jsonb_build_object('id', p.id, 'title', p.title) AS data
FROM tb_post p;

CREATE INDEX ix_tv_post_title ON tv_post (title);

CREATE INDEX ix_tv_post_lookup ON tv_post (title);
