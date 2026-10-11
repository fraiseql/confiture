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
SELECT p.pk_post, p.id, p.title, p.body,
       jsonb_build_object('id', p.id, 'title', p.title, 'body', p.body) AS data
FROM tb_post p;

CREATE INDEX ix_tv_post_body ON tv_post (body);

CREATE INDEX ix_tv_post_lookup ON tv_post (id, title);

CREATE TABLE tv_author AS
SELECT a.pk_author, a.id, a.name, jsonb_build_object('id', a.id, 'name', a.name) AS data
FROM tb_author a;

CREATE INDEX ix_tv_author_name ON tv_author (name);
