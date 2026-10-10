-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE SCHEMA IF NOT EXISTS ren;

-- confiture:tier additive
CREATE TYPE mood AS ENUM ('sad', 'ok');

-- confiture:tier additive
CREATE TYPE retired_status AS ENUM ('a', 'b');

-- confiture:tier additive
CREATE SEQUENCE IF NOT EXISTS retired_seq;

-- confiture:creates legacy
-- confiture:tier additive
CREATE TABLE legacy (
    id INTEGER NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:creates ordered
-- confiture:tier additive
CREATE TABLE ordered (
    a INTEGER,
    b INTEGER
);

-- confiture:creates parent
-- confiture:tier additive
CREATE TABLE parent (
    id INTEGER NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:creates people
-- confiture:tier additive
CREATE TABLE people (
    id INTEGER NOT NULL,
    full_name TEXT,
    PRIMARY KEY (id)
);

-- confiture:creates rekeyed
-- confiture:tier additive
CREATE TABLE rekeyed (
    a INTEGER NOT NULL,
    b INTEGER NOT NULL,
    CONSTRAINT rekeyed_pk PRIMARY KEY (a)
);

-- confiture:creates things
-- confiture:tier lock_risky
CREATE TABLE things (
    id INTEGER NOT NULL,
    legacy_flag BOOLEAN,
    size VARCHAR(50),
    note TEXT NOT NULL,
    status TEXT DEFAULT 'new',
    pid INTEGER,
    code TEXT,
    qty INTEGER NOT NULL,
    span TSRANGE,
    PRIMARY KEY (id),
    CONSTRAINT things_old_fk FOREIGN KEY (pid) REFERENCES parent (id),
    CONSTRAINT things_old_uq UNIQUE (code),
    CONSTRAINT things_old_ck CHECK (qty > 0),
    CONSTRAINT things_old_ex EXCLUDE USING gist (span WITH &&)
);
CREATE INDEX IF NOT EXISTS things_old_ix ON things (code);

-- confiture:creates ren.tb_orders_archive
-- confiture:tier additive
CREATE TABLE ren.tb_orders_archive (
    id INTEGER NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_retired AS SELECT 1 AS one;

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_things AS SELECT id FROM things;
