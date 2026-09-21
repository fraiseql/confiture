-- The other side of old.sql: every kind of schema change, once each.

CREATE TYPE mood AS ENUM ('sad', 'ok', 'happy');
CREATE TYPE new_status AS ENUM ('x', 'y');
CREATE SEQUENCE new_seq;

CREATE SCHEMA ren;
CREATE TABLE ren.tb_orders_history (id INT PRIMARY KEY);

CREATE TABLE audit (id INT PRIMARY KEY, at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE parent (id INT PRIMARY KEY);

CREATE TABLE people (
    id INT PRIMARY KEY,
    display_name TEXT
);

CREATE TABLE things (
    id INT PRIMARY KEY,
    created_at TIMESTAMPTZ,
    size VARCHAR(100),
    note TEXT,
    status TEXT DEFAULT 'open',
    pid INT,
    code TEXT,
    qty INT,
    CONSTRAINT things_new_fk FOREIGN KEY (pid) REFERENCES parent (id) ON DELETE CASCADE,
    CONSTRAINT things_new_ck CHECK (qty >= 0),
    CONSTRAINT things_new_uq UNIQUE (code, qty)
);
CREATE INDEX things_new_ix ON things (code, qty);

CREATE VIEW v_added AS SELECT 2 AS two;
CREATE VIEW v_things AS SELECT id, code FROM things;
