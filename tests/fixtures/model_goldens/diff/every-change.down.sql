-- Migration: golden
-- Version: <version>

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_things AS SELECT id FROM things;

-- confiture:tier destructive
DROP VIEW IF EXISTS v_added;

-- confiture:tier lock_risky
ALTER TABLE things ADD CONSTRAINT things_old_uq UNIQUE (code);

-- confiture:tier destructive
ALTER TABLE things DROP CONSTRAINT IF EXISTS things_new_uq;

-- confiture:tier lock_risky
ALTER TABLE things ADD CONSTRAINT things_old_ck CHECK (qty > 0);

-- confiture:tier destructive
ALTER TABLE things DROP CONSTRAINT IF EXISTS things_new_ck;

-- confiture:tier reversible
ALTER TABLE things ADD CONSTRAINT things_old_fk FOREIGN KEY (pid) REFERENCES parent (id) NOT VALID;
ALTER TABLE things VALIDATE CONSTRAINT things_old_fk;

-- confiture:tier destructive
ALTER TABLE things DROP CONSTRAINT IF EXISTS things_new_fk;

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS things_old_ix ON things (code);

-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS things_new_ix;

-- confiture:tier reversible
ALTER TABLE things ALTER COLUMN status SET DEFAULT 'new';

ALTER TABLE things ALTER COLUMN size TYPE VARCHAR(50);

-- confiture:tier lock_risky
ALTER TABLE things ALTER COLUMN note SET NOT NULL;

-- confiture:tier irreversible
ALTER TABLE things DROP COLUMN created_at;

-- confiture:tier additive
ALTER TABLE things ADD COLUMN legacy_flag BOOLEAN;

-- confiture:tier reversible
ALTER TABLE people RENAME COLUMN display_name TO full_name;

-- confiture:tier irreversible
DROP TABLE audit;

-- confiture:tier reversible
ALTER TABLE ren.tb_orders_history RENAME TO tb_orders_archive;

-- confiture:tier irreversible
DROP SEQUENCE IF EXISTS new_seq;

-- confiture:irreversible no rollback derived for CHANGE_ENUM_VALUES mood

-- confiture:tier destructive
DROP TYPE IF EXISTS new_status;

-- confiture:tier additive
CREATE SEQUENCE IF NOT EXISTS retired_seq;

-- confiture:tier additive
CREATE TYPE retired_status AS ENUM ('a', 'b');

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS legacy (
    id INTEGER NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_retired AS SELECT 1 AS one;
