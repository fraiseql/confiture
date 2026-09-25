-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS catalog.tb_product (
    id UUID NOT NULL,
    pk_product BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY,
    fk_vendor BIGINT NOT NULL,
    name TEXT NOT NULL,
    price NUMERIC(10,2) NOT NULL,
    status catalog.product_status NOT NULL DEFAULT 'draft',
    PRIMARY KEY (pk_product),
    FOREIGN KEY (fk_vendor) REFERENCES catalog.tb_vendor (pk_vendor),
    UNIQUE (id),
    CHECK (price > 0)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS catalog.tb_vendor (
    id UUID NOT NULL,
    pk_vendor BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL,
    country_code VARCHAR(2) NOT NULL,
    PRIMARY KEY (pk_vendor),
    UNIQUE (id)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS prep_seed.tb_product (
    id UUID NOT NULL,
    fk_vendor_id UUID NOT NULL,
    name TEXT NOT NULL,
    price NUMERIC(10,2) NOT NULL,
    status catalog.product_status NOT NULL DEFAULT 'draft',
    PRIMARY KEY (id),
    FOREIGN KEY (fk_vendor_id) REFERENCES prep_seed.tb_vendor (id),
    CHECK (price > 0)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS prep_seed.tb_vendor (
    id UUID NOT NULL,
    name TEXT NOT NULL,
    country_code VARCHAR(2) NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:tier additive
CREATE TYPE catalog.product_status AS ENUM ('draft', 'active', 'retired');

-- confiture:tier reversible
CREATE OR REPLACE FUNCTION fn_resolve_tb_product() RETURNS void AS $$
BEGIN
    INSERT INTO catalog.tb_product (id, fk_vendor, name, price, status)
    SELECT prep.id, vendor.pk_vendor, prep.name, prep.price, prep.status
    FROM prep_seed.tb_product prep
    LEFT JOIN catalog.tb_vendor vendor ON vendor.id = prep.fk_vendor_id
    ON CONFLICT (id) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

-- confiture:tier reversible
CREATE OR REPLACE FUNCTION fn_resolve_tb_vendor() RETURNS void AS $$
BEGIN
    INSERT INTO catalog.tb_vendor (id, name, country_code)
    SELECT prep.id, prep.name, prep.country_code
    FROM prep_seed.tb_vendor prep
    ON CONFLICT (id) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

-- confiture:tier additive
CREATE SCHEMA IF NOT EXISTS catalog;

-- confiture:tier additive
CREATE SCHEMA IF NOT EXISTS prep_seed;
