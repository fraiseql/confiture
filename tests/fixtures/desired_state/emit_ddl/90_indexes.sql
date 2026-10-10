-- 90_indexes.sql
CREATE INDEX IF NOT EXISTS "ix_tv_product_name_fr" ON "tv_product" (((data->'name'->>'fr') COLLATE "fr-x-icu"));
CREATE INDEX IF NOT EXISTS "ix_tb_post_title" ON "tb_post" ((lower(title)));
