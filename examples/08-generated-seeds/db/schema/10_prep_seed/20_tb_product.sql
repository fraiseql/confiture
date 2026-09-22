-- A product references its vendor by the vendor's UUID.
CREATE TABLE prep_seed.tb_product (
    id UUID PRIMARY KEY,
    fk_vendor_id UUID NOT NULL REFERENCES prep_seed.tb_vendor (id),
    name TEXT NOT NULL,
    price NUMERIC(10, 2) NOT NULL CHECK (price > 0),
    status catalog.product_status NOT NULL DEFAULT 'draft'
);
