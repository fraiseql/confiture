-- A counterparty: this tenant's relation with a company. Each tenant keeps
-- its own terms; the company itself is global. No column here references
-- management.tb_organization except tenant_id.
CREATE TABLE app.tb_provider (
    tenant_id  uuid NOT NULL REFERENCES management.tb_organization (id),
    id         uuid NOT NULL,
    fk_company uuid NOT NULL REFERENCES catalog.tb_company (id),
    terms      text,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, fk_company)
);
COMMENT ON TABLE app.tb_provider IS 'A company a tenant buys from, on that tenant''s terms';
