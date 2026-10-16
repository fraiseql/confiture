-- An aggregate TVIEW: pg_tviews_create() with group_keys (pg_tviews_create_aggregate is gone).
CREATE TABLE tb_user (pk_user bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, name text NOT NULL);
CREATE TABLE tb_order (
    pk_order bigint PRIMARY KEY, id uuid NOT NULL UNIQUE,
    fk_user bigint NOT NULL REFERENCES tb_user, total numeric NOT NULL
);
SELECT tviews.pg_tviews_create('tv_user_summary', $q$
SELECT o.fk_user AS pk_user_summary, u.id,
       jsonb_build_object('orders', count(*), 'total', sum(o.total)) AS data
FROM tb_order o JOIN tb_user u ON u.pk_user = o.fk_user
GROUP BY o.fk_user, u.id$q$, '{"group_keys": {"tb_order": "fk_user", "tb_user": "pk_user"}}');
