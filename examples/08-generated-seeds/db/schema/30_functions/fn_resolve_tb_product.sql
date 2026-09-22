-- prep_seed.tb_product → catalog.tb_product: the vendor's UUID becomes its BIGINT key.
-- Runs after fn_resolve_tb_vendor, whose rows it joins.
CREATE OR REPLACE FUNCTION fn_resolve_tb_product()
RETURNS void AS $$
BEGIN
    INSERT INTO catalog.tb_product (id, fk_vendor, name, price, status)
    SELECT prep.id, vendor.pk_vendor, prep.name, prep.price, prep.status
    FROM prep_seed.tb_product prep
    LEFT JOIN catalog.tb_vendor vendor ON vendor.id = prep.fk_vendor_id
    ON CONFLICT (id) DO NOTHING;
END;
$$ LANGUAGE plpgsql;
