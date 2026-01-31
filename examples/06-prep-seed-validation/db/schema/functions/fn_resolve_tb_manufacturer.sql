-- Resolution function: Transform prep_seed.tb_manufacturer → catalog.tb_manufacturer
-- Converts UUID identifiers to BIGINT via hash function
CREATE OR REPLACE FUNCTION fn_resolve_tb_manufacturer()
RETURNS void AS $$
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

COMMENT ON FUNCTION fn_resolve_tb_manufacturer() IS
'Transforms prep_seed.tb_manufacturer data to catalog.tb_manufacturer.
Does NOT modify any foreign keys (this table has none).
Cleans up prep_seed data after resolution.';
