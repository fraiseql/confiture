-- A tenant's own units, beside the standard ones.
CREATE TABLE app.tb_custom_unit (
    tenant_id uuid NOT NULL REFERENCES management.tb_organization (id),
    id        uuid NOT NULL,
    code      text NOT NULL,
    label     text NOT NULL,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, code)
);
COMMENT ON TABLE app.tb_custom_unit IS 'Units of measure a tenant defines for itself';
