CREATE TABLE catalog.tb_product (
    id   uuid PRIMARY KEY,
    sku  text NOT NULL UNIQUE,
    name text NOT NULL
);
COMMENT ON TABLE catalog.tb_product IS 'Products every tenant can order';
