-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE SCHEMA IF NOT EXISTS ren;

-- confiture:tier additive
CREATE TYPE mood AS ENUM ('sad', 'ok', 'happy');

-- confiture:tier additive
CREATE TYPE new_status AS ENUM ('x', 'y');

-- confiture:tier additive
CREATE SEQUENCE IF NOT EXISTS new_seq;

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

-- confiture:tier lock_risky
CREATE TABLE IF NOT EXISTS things (
    id INTEGER NOT NULL,
    created_at TIMESTAMPTZ,
    size VARCHAR(100),
    note TEXT,
    status TEXT DEFAULT 'open',
    pid INTEGER,
    code TEXT,
    qty INTEGER,
    span TSRANGE,
    PRIMARY KEY (id),
    CONSTRAINT things_new_fk FOREIGN KEY (pid) REFERENCES parent (id) ON DELETE CASCADE,
    CONSTRAINT things_new_uq UNIQUE (code, qty),
    CONSTRAINT things_new_ck CHECK (qty >= 0),
    CONSTRAINT things_new_ex EXCLUDE USING gist (span WITH &&) WHERE (qty > 0)
);
CREATE INDEX IF NOT EXISTS things_new_ix ON things (code, qty);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS ren.tb_orders_history (
    id INTEGER NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_added AS SELECT 2 AS two;

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_things AS SELECT id, code FROM things;
