-- Migration: golden
-- Version: <version>

-- confiture:tier destructive
DROP FUNCTION IF EXISTS fn_resolve_tb_vendor();

-- confiture:tier destructive
DROP FUNCTION IF EXISTS fn_resolve_tb_product();

-- confiture:tier irreversible
DROP TABLE prep_seed.tb_product;

-- confiture:tier irreversible
DROP TABLE prep_seed.tb_vendor;

-- confiture:tier irreversible
DROP TABLE catalog.tb_product;

-- confiture:tier irreversible
DROP TABLE catalog.tb_vendor;

-- confiture:tier destructive
DROP TYPE IF EXISTS catalog.product_status;

-- confiture:tier irreversible
DROP SCHEMA IF EXISTS prep_seed;

-- confiture:tier irreversible
DROP SCHEMA IF EXISTS catalog;
