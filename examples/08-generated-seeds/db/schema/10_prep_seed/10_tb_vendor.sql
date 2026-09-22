-- Seeds land here: UUID keys, which a generator can write before any row exists.
CREATE TABLE prep_seed.tb_vendor (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    country_code VARCHAR(2) NOT NULL
);
