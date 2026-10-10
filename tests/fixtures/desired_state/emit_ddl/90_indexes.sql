-- 90_indexes.sql
CREATE INDEX IF NOT EXISTS "ix_tv_product_name_fr" ON "tv_product" (((data->'name'->>'fr') COLLATE "fr-x-icu"));
