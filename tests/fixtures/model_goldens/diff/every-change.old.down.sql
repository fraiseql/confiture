-- Migration: golden
-- Version: <version>

-- confiture:tier destructive
DROP VIEW IF EXISTS v_things;

-- confiture:tier destructive
DROP VIEW IF EXISTS v_retired;

-- confiture:tier irreversible
DROP SCHEMA IF EXISTS ren;

-- confiture:tier irreversible
DROP SEQUENCE IF EXISTS retired_seq;

-- confiture:tier destructive
DROP TYPE IF EXISTS retired_status;

-- confiture:tier destructive
DROP TYPE IF EXISTS mood;

-- confiture:tier irreversible
DROP TABLE ren.tb_orders_archive;

-- confiture:tier irreversible
DROP TABLE things;

-- confiture:tier irreversible
DROP TABLE people;

-- confiture:tier irreversible
DROP TABLE parent;

-- confiture:tier irreversible
DROP TABLE legacy;
