CREATE SCHEMA management;
COMMENT ON SCHEMA management IS 'The table of tenants';

CREATE SCHEMA catalog;
COMMENT ON SCHEMA catalog IS 'Reference data shared by every tenant';

CREATE SCHEMA app;
COMMENT ON SCHEMA app IS 'Tenant data: every table carries tenant_id';
