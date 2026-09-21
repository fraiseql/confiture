-- Migration: golden
-- Version: <version>

-- confiture:irreversible no rollback derived for ADD_SCHEMA prep_seed

-- confiture:irreversible no rollback derived for ADD_SCHEMA catalog

-- confiture:tier destructive
DROP FUNCTION IF EXISTS fn_resolve_tb_manufacturer();

-- confiture:tier irreversible
DROP TABLE prep_seed.tb_manufacturer;

-- confiture:tier irreversible
DROP TABLE catalog.tb_manufacturer;
