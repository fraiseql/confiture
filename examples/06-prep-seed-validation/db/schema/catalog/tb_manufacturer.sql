-- Final table: manufacturer with BIGINT IDs (trinity pattern)
-- Trinity pattern: id UUID, pk_* BIGINT, fk_* BIGINT
CREATE TABLE catalog.tb_manufacturer (
    id UUID NOT NULL UNIQUE,
    pk_manufacturer BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL,
    country_code VARCHAR(2) NOT NULL
);

-- Create indexes for lookups
CREATE INDEX idx_catalog_tb_manufacturer_name ON catalog.tb_manufacturer(name);
CREATE INDEX idx_catalog_tb_manufacturer_id ON catalog.tb_manufacturer(id);
