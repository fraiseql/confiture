-- Migration: golden
-- Version: <version>

-- confiture:destructive
-- confiture:tier destructive
DROP VIEW IF EXISTS v_retired;

-- confiture:irreversible data
-- confiture:tier irreversible
DROP TABLE legacy;

-- confiture:tier destructive
DROP TYPE IF EXISTS retired_status;

-- confiture:irreversible data
-- confiture:tier irreversible
DROP SEQUENCE IF EXISTS retired_seq;

-- confiture:tier additive
CREATE TYPE new_status AS ENUM ('x', 'y');

-- confiture:irreversible no rollback derived for CHANGE_ENUM_VALUES mood
-- confiture:tier irreversible
ALTER TYPE mood ADD VALUE IF NOT EXISTS 'happy';

-- confiture:tier additive
CREATE SEQUENCE IF NOT EXISTS new_seq;

-- confiture:tier reversible
ALTER TABLE ren.tb_orders_archive RENAME TO tb_orders_history;

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER NOT NULL,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

-- confiture:tier reversible
ALTER TABLE people RENAME COLUMN full_name TO display_name;

-- confiture:irreversible data
-- confiture:tier irreversible
ALTER TABLE things DROP COLUMN legacy_flag;

-- confiture:tier additive
ALTER TABLE things ADD COLUMN created_at TIMESTAMPTZ;

-- confiture:tier reversible
ALTER TABLE things ALTER COLUMN note DROP NOT NULL;

ALTER TABLE things ALTER COLUMN size TYPE VARCHAR(100);

-- confiture:tier reversible
ALTER TABLE things ALTER COLUMN status SET DEFAULT 'open';

-- confiture:tier additive
CREATE INDEX CONCURRENTLY IF NOT EXISTS things_new_ix ON things (code, qty);

-- confiture:tier destructive
DROP INDEX CONCURRENTLY IF EXISTS things_old_ix;

-- confiture:tier reversible
ALTER TABLE things ADD CONSTRAINT things_new_fk FOREIGN KEY (pid) REFERENCES parent (id) ON DELETE CASCADE NOT VALID;
ALTER TABLE things VALIDATE CONSTRAINT things_new_fk;

-- confiture:tier destructive
ALTER TABLE things DROP CONSTRAINT IF EXISTS things_old_fk;

-- confiture:tier lock_risky
ALTER TABLE things ADD CONSTRAINT things_new_ck CHECK (qty >= 0);

-- confiture:tier destructive
ALTER TABLE things DROP CONSTRAINT IF EXISTS things_old_ck;

-- confiture:tier lock_risky
ALTER TABLE things ADD CONSTRAINT things_new_uq UNIQUE (code, qty);

-- confiture:tier destructive
ALTER TABLE things DROP CONSTRAINT IF EXISTS things_old_uq;

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_added AS SELECT 2 AS two;

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_things AS SELECT id, code FROM things;
