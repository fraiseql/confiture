-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER NOT NULL,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
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
    display_name TEXT,
    PRIMARY KEY (id)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS things (
    id INTEGER NOT NULL,
    created_at TIMESTAMPTZ,
    size VARCHAR(100),
    note TEXT,
    status TEXT DEFAULT 'open',
    pid INTEGER,
    code TEXT,
    qty INTEGER,
    PRIMARY KEY (id),
    CONSTRAINT things_new_fk FOREIGN KEY (pid) REFERENCES parent (id) ON DELETE CASCADE,
    CONSTRAINT things_new_uq UNIQUE (code, qty),
    CONSTRAINT things_new_ck CHECK (qty >= 0)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS ren.tb_orders_history (
    id INTEGER NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:tier additive
CREATE TYPE mood AS ENUM ('sad', 'ok', 'happy');

-- confiture:tier additive
CREATE TYPE new_status AS ENUM ('x', 'y');

-- confiture:tier additive
CREATE SEQUENCE IF NOT EXISTS new_seq;

-- WARNING: no SQL derived for: ADD SCHEMA ren. Edit this file before deploying.

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_added AS SELECT 2 AS two;

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_things AS SELECT id, code FROM things;
