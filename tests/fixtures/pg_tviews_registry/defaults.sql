-- A TVIEW that declares nothing: every option at pg_tviews' default (LOGGED, fillfactor 85).
CREATE TABLE tb_user (pk_user bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, name text);
CREATE TABLE tb_post (
    pk_post bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, fk_user bigint REFERENCES tb_user, title text
);
CREATE TABLE tv_post AS
SELECT p.pk_post, p.id, jsonb_build_object('id', p.id, 'author', u.name) AS data
FROM tb_post p JOIN tb_user u ON u.pk_user = p.fk_user;
