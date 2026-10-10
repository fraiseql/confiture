-- Migration: init_from_spec
-- Version: 20260101000000

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS tb_post (
    id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    score DOUBLE PRECISION
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS tb_user (
    id INTEGER NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT,
    is_active BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

-- confiture:tier additive
-- tv_product is not declared in this schema: the index assumes it exists
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tv_product_name_fr ON tv_product ((((data -> 'name') ->> 'fr') COLLATE "fr-x-icu"));
