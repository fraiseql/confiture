-- The final table: the trinity pattern, a BIGINT key PostgreSQL generates.
CREATE TABLE catalog.tb_vendor (
    id UUID NOT NULL UNIQUE,
    pk_vendor BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    country_code VARCHAR(2) NOT NULL
);
