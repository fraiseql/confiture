-- Migration: golden
-- Version: <version>

-- confiture:tier irreversible
DROP SCHEMA IF EXISTS prep_seed;

-- confiture:tier irreversible
DROP SCHEMA IF EXISTS catalog;

-- confiture:tier destructive
DROP FUNCTION IF EXISTS fn_resolve_tb_manufacturer();

-- confiture:tier irreversible
DROP TABLE prep_seed.tb_manufacturer;

-- confiture:tier irreversible
DROP TABLE catalog.tb_manufacturer;
