-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS catalog.tb_manufacturer (
    id UUID NOT NULL,
    pk_manufacturer BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL,
    country_code VARCHAR(2) NOT NULL,
    PRIMARY KEY (pk_manufacturer),
    UNIQUE (id)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS prep_seed.tb_manufacturer (
    id UUID NOT NULL,
    name TEXT NOT NULL,
    country_code VARCHAR(2) NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:tier reversible
CREATE OR REPLACE FUNCTION fn_resolve_tb_manufacturer() RETURNS void AS $$
BEGIN
    -- Insert from prep_seed to catalog
    -- Note: GENERATED ALWAYS AS IDENTITY handles pk_manufacturer
    INSERT INTO catalog.tb_manufacturer (id, name, country_code)
    SELECT
        prep.id,
        prep.name,
        prep.country_code
    FROM prep_seed.tb_manufacturer prep
    ON CONFLICT (id) DO NOTHING;  -- Handle duplicates gracefully

    -- Clear prep_seed table after resolution
    TRUNCATE TABLE prep_seed.tb_manufacturer;
END;
$$ LANGUAGE plpgsql;

-- WARNING: no SQL derived for: ADD SCHEMA catalog. Edit this file before deploying.

-- WARNING: no SQL derived for: ADD SCHEMA prep_seed. Edit this file before deploying.
