-- The root: one row per tenant. Its primary key is the tenant id every
-- tenant_id column references.
CREATE TABLE management.tb_organization (
    id   uuid PRIMARY KEY,
    name text NOT NULL
);
COMMENT ON TABLE management.tb_organization IS 'One row per tenant; id is the tenant id';
