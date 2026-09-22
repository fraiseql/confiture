-- The two schemas of the prep-seed pattern, and the one type both use.
CREATE SCHEMA prep_seed;
CREATE SCHEMA catalog;

CREATE TYPE catalog.product_status AS ENUM ('draft', 'active', 'retired');
