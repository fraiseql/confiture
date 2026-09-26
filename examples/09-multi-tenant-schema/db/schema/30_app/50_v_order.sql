-- Publishes tenant_id as a plain column, so a reader can filter on it.
CREATE VIEW app.v_order AS
SELECT o.tenant_id,
       o.id,
       o.reference,
       o.created_at,
       p.id AS provider_id,
       c.legal_name AS provider_name
FROM app.tb_order o
JOIN app.tb_provider p ON p.tenant_id = o.tenant_id AND p.id = o.fk_provider
JOIN catalog.tb_company c ON c.id = p.fk_company;
COMMENT ON VIEW app.v_order IS 'Orders with their provider, one tenant per tenant_id';
