-- The final product: its vendor by BIGINT key, resolved from the UUID.
CREATE TABLE catalog.tb_product (
    id UUID NOT NULL UNIQUE,
    pk_product BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fk_vendor BIGINT NOT NULL REFERENCES catalog.tb_vendor (pk_vendor),
    name TEXT NOT NULL,
    price NUMERIC(10, 2) NOT NULL CHECK (price > 0),
    status catalog.product_status NOT NULL DEFAULT 'draft'
);
