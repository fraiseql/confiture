CREATE FUNCTION app.fn_create_order(p_tenant_id uuid, p_provider uuid, p_reference text)
RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
    v_id uuid := gen_random_uuid();
BEGIN
    INSERT INTO app.tb_order (tenant_id, id, fk_provider, reference)
    VALUES (p_tenant_id, v_id, p_provider, p_reference);
    RETURN v_id;
END;
$$;
COMMENT ON FUNCTION app.fn_create_order(uuid, uuid, text) IS 'Place an order for one tenant';
