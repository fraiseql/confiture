-- Prep-seed table: manufacturer with UUID IDs and foreign keys
-- Used for initial data seeding (easier to reference UUIDs)
CREATE TABLE prep_seed.tb_manufacturer (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    country_code VARCHAR(2) NOT NULL
);

-- Create index on name for lookups
CREATE INDEX idx_prep_tb_manufacturer_name ON prep_seed.tb_manufacturer(name);
