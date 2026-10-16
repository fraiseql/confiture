-- The storage a CREATE TABLE … AS can say: UNLOGGED and a fillfactor.
CREATE TABLE tb_post (pk_post bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, title text);
CREATE UNLOGGED TABLE tv_post WITH (fillfactor = 70) AS
SELECT p.pk_post, p.id, jsonb_build_object('id', p.id, 'title', p.title) AS data
FROM tb_post p;
