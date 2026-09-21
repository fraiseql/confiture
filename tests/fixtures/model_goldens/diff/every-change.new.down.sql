-- Migration: golden
-- Version: <version>

-- confiture:tier destructive
DROP VIEW IF EXISTS v_things;

-- confiture:tier destructive
DROP VIEW IF EXISTS v_added;

-- confiture:irreversible no rollback derived for ADD_SCHEMA ren

-- confiture:tier irreversible
DROP SEQUENCE IF EXISTS new_seq;

-- confiture:tier destructive
DROP TYPE IF EXISTS new_status;

-- confiture:tier destructive
DROP TYPE IF EXISTS mood;

-- confiture:tier irreversible
DROP TABLE ren.tb_orders_history;

-- confiture:tier irreversible
DROP TABLE things;

-- confiture:tier irreversible
DROP TABLE people;

-- confiture:tier irreversible
DROP TABLE parent;

-- confiture:tier irreversible
DROP TABLE audit;
