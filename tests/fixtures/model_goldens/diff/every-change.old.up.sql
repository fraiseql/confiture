-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS legacy (
    id INTEGER NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS parent (
    id INTEGER NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS people (
    id INTEGER NOT NULL,
    full_name TEXT,
    PRIMARY KEY (id)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS things (
    id INTEGER NOT NULL,
    legacy_flag BOOLEAN,
    size VARCHAR(50),
    note TEXT NOT NULL,
    status TEXT DEFAULT 'new',
    pid INTEGER,
    code TEXT,
    qty INTEGER,
    PRIMARY KEY (id),
    CONSTRAINT things_old_fk FOREIGN KEY (pid) REFERENCES parent (id),
    CONSTRAINT things_old_uq UNIQUE (code),
    CONSTRAINT things_old_ck CHECK (qty > 0)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS ren.tb_orders_archive (
    id INTEGER NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:tier additive
CREATE TYPE mood AS ENUM ('sad', 'ok');

-- confiture:tier additive
CREATE TYPE retired_status AS ENUM ('a', 'b');

-- confiture:tier additive
CREATE SEQUENCE IF NOT EXISTS retired_seq;

-- WARNING: no SQL derived for: ADD SCHEMA ren. Edit this file before deploying.

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_retired AS SELECT 1 AS one;

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_things AS SELECT id FROM things;
