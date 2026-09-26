-- The standard units, fanned out to every tenant, beside each tenant's own.
-- A filter on tenant_id keeps the standard rows and that tenant's units.
CREATE VIEW app.v_unit AS
SELECT o.id AS tenant_id, u.id, u.code, u.label, false AS is_custom
FROM catalog.tb_unit u
CROSS JOIN management.tb_organization o
UNION ALL
SELECT c.tenant_id, c.id, c.code, c.label, true
FROM app.tb_custom_unit c;
COMMENT ON VIEW app.v_unit IS 'Every unit a tenant can use: the standard ones and its own';
