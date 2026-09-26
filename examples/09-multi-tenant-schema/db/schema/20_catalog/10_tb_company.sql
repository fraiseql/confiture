-- A directory of companies, global: a company's identity is stored once,
-- whichever tenants deal with it.
CREATE TABLE catalog.tb_company (
    id         uuid PRIMARY KEY,
    legal_name text NOT NULL,
    vat_id     text UNIQUE
);
COMMENT ON TABLE catalog.tb_company IS 'Companies any tenant may trade with';
