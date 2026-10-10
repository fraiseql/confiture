-- Migration: init_from_spec
-- Version: 20260101000000

-- confiture:tier destructive
-- tv_product is not declared in this schema: the index assumes it exists
DROP INDEX CONCURRENTLY IF EXISTS ix_tv_product_name_fr;

-- confiture:tier irreversible
DROP TABLE tb_user;

-- confiture:tier irreversible
DROP TABLE tb_post;
