CREATE TABLE app.tb_order (
    tenant_id   uuid NOT NULL REFERENCES management.tb_organization (id),
    id          uuid NOT NULL,
    fk_provider uuid NOT NULL,
    reference   text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    -- two tenants may both use the reference 'PO-1'
    UNIQUE (tenant_id, reference),
    -- the provider is one of this tenant's providers, and PostgreSQL checks it
    FOREIGN KEY (tenant_id, fk_provider) REFERENCES app.tb_provider (tenant_id, id)
);
COMMENT ON TABLE app.tb_order IS 'A purchase order a tenant places with one of its providers';

-- Not unique, so not judged: a sweep across tenants by age wants it.
CREATE INDEX ix_order_created_at ON app.tb_order (created_at);

CREATE TABLE app.tb_order_line (
    tenant_id  uuid NOT NULL REFERENCES management.tb_organization (id),
    id         uuid NOT NULL,
    fk_order   uuid NOT NULL,
    fk_product uuid NOT NULL REFERENCES catalog.tb_product (id),
    quantity   integer NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, fk_order) REFERENCES app.tb_order (tenant_id, id)
);
COMMENT ON TABLE app.tb_order_line IS 'One product on an order';

-- fk_order determines tenant_id. For a filter on both (tenant_id = $1 AND
-- fk_order = $2) the planner otherwise multiplies the two selectivities as if
-- they were independent. A join on both is estimated from the foreign key.
CREATE STATISTICS app.st_order_line_tenant_order (dependencies)
    ON tenant_id, fk_order FROM app.tb_order_line;
