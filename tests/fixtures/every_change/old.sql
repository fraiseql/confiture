-- One side of a pair whose diff emits every kind of schema change the differ
-- knows, once each (tests/unit/test_schema_change_is_exhaustive.py holds that).
-- The other side is new.sql; neither is a schema anyone would write.

CREATE TYPE mood AS ENUM ('sad', 'ok');
CREATE TYPE retired_status AS ENUM ('a', 'b');
CREATE SEQUENCE retired_seq;

-- A rename is paired within one schema, and only there.
CREATE SCHEMA ren;
CREATE TABLE ren.tb_orders_archive (id INT PRIMARY KEY);

CREATE TABLE legacy (id INT PRIMARY KEY);
CREATE TABLE parent (id INT PRIMARY KEY);

CREATE TABLE people (
    id INT PRIMARY KEY,
    full_name TEXT
);

CREATE TABLE things (
    id INT PRIMARY KEY,
    legacy_flag BOOLEAN,
    size VARCHAR(50),
    note TEXT NOT NULL,
    status TEXT DEFAULT 'new',
    pid INT,
    code TEXT,
    qty INT,
    CONSTRAINT things_old_fk FOREIGN KEY (pid) REFERENCES parent (id),
    CONSTRAINT things_old_ck CHECK (qty > 0),
    CONSTRAINT things_old_uq UNIQUE (code)
);
CREATE INDEX things_old_ix ON things (code);

CREATE VIEW v_retired AS SELECT 1 AS one;
CREATE VIEW v_things AS SELECT id FROM things;
