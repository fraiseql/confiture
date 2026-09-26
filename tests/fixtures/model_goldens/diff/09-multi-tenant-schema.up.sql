-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE SCHEMA IF NOT EXISTS app;

-- confiture:tier additive
CREATE SCHEMA IF NOT EXISTS catalog;

-- confiture:tier additive
CREATE SCHEMA IF NOT EXISTS management;

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS catalog.tb_company (
    id UUID NOT NULL,
    legal_name TEXT NOT NULL,
    vat_id TEXT,
    PRIMARY KEY (id),
    UNIQUE (vat_id)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS catalog.tb_product (
    id UUID NOT NULL,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (sku)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS catalog.tb_unit (
    id UUID NOT NULL,
    code TEXT NOT NULL,
    label TEXT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (code)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS management.tb_organization (
    id UUID NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (id)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS app.tb_custom_unit (
    tenant_id UUID NOT NULL,
    id UUID NOT NULL,
    code TEXT NOT NULL,
    label TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id) REFERENCES management.tb_organization (id),
    UNIQUE (tenant_id, code)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS app.tb_provider (
    tenant_id UUID NOT NULL,
    id UUID NOT NULL,
    fk_company UUID NOT NULL,
    terms TEXT,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id) REFERENCES management.tb_organization (id),
    FOREIGN KEY (fk_company) REFERENCES catalog.tb_company (id),
    UNIQUE (tenant_id, fk_company)
);

-- confiture:tier lock_risky
CREATE TABLE IF NOT EXISTS app.tb_order (
    tenant_id UUID NOT NULL,
    id UUID NOT NULL,
    fk_provider UUID NOT NULL,
    reference TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id) REFERENCES management.tb_organization (id),
    FOREIGN KEY (tenant_id, fk_provider) REFERENCES app.tb_provider (tenant_id, id),
    UNIQUE (tenant_id, reference)
);
CREATE INDEX IF NOT EXISTS ix_order_created_at ON app.tb_order (created_at);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS app.tb_order_line (
    tenant_id UUID NOT NULL,
    id UUID NOT NULL,
    fk_order UUID NOT NULL,
    fk_product UUID NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id) REFERENCES management.tb_organization (id),
    FOREIGN KEY (fk_product) REFERENCES catalog.tb_product (id),
    FOREIGN KEY (tenant_id, fk_order) REFERENCES app.tb_order (tenant_id, id),
    CHECK (quantity > 0)
);

-- confiture:tier reversible
CREATE OR REPLACE FUNCTION app.fn_create_order(p_tenant_id uuid, p_provider uuid, p_reference text) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE
    v_id uuid := gen_random_uuid();
BEGIN
    INSERT INTO app.tb_order (tenant_id, id, fk_provider, reference)
    VALUES (p_tenant_id, v_id, p_provider, p_reference);
    RETURN v_id;
END;
$$;

-- confiture:tier reversible
CREATE OR REPLACE VIEW app.v_order AS SELECT o.tenant_id, o.id, o.reference, o.created_at, p.id AS provider_id, c.legal_name AS provider_name FROM app.tb_order AS o INNER JOIN app.tb_provider AS p ON p.tenant_id = o.tenant_id AND p.id = o.fk_provider INNER JOIN catalog.tb_company AS c ON c.id = p.fk_company;

-- confiture:tier reversible
CREATE OR REPLACE VIEW app.v_unit AS SELECT o.id AS tenant_id, u.id, u.code, u.label, FALSE AS is_custom FROM catalog.tb_unit AS u CROSS JOIN management.tb_organization AS o UNION ALL SELECT c.tenant_id, c.id, c.code, c.label, TRUE FROM app.tb_custom_unit AS c;

-- WARNING: no SQL derived for: ADD STATISTICS app.st_order_line_tenant_order. Edit this file before deploying.
