-- prep_seed.tb_vendor → catalog.tb_vendor; PostgreSQL generates pk_vendor.
CREATE OR REPLACE FUNCTION fn_resolve_tb_vendor()
RETURNS void AS $$
BEGIN
    INSERT INTO catalog.tb_vendor (id, name, country_code)
    SELECT prep.id, prep.name, prep.country_code
    FROM prep_seed.tb_vendor prep
    ON CONFLICT (id) DO NOTHING;
END;
$$ LANGUAGE plpgsql;
