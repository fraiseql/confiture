-- Issue #302: the column types whose expected and live spellings disagreed.
-- Eight of these produced a `type_mismatch` warning on a database applied
-- verbatim from this DDL; the rest are controls that always agreed.
CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;

CREATE DOMAIN core.pos AS INTEGER CHECK (VALUE > 0);

CREATE TYPE core.mood AS ENUM ('sad', 'ok', 'happy');

CREATE TABLE core.tb_types (
    id BIGSERIAL PRIMARY KEY,
    counter SERIAL NOT NULL,
    label VARCHAR(50) NOT NULL,
    tags TEXT[],
    scores INT[],
    grid INTEGER[][],
    doc JSON,
    flags BIT(3),
    vflags BIT VARYING(8),
    email public.CITEXT,
    amount NUMERIC(10, 2),
    amounts NUMERIC(10, 2)[],
    code CHAR(4),
    seen_at TIMESTAMPTZ,
    rank core.pos,
    feeling core.mood,
    -- The four spellings `canonical_type` could not parse back from
    -- `format_type`: its regex wants the typmod last, so a parameterised
    -- temporal falls through unparsed, `varbit` has no alias, and a bare
    -- `char` is `character(1)` on the other side (REVIEW B5).
    ts3 TIMESTAMP(3),
    t3 TIME(3),
    vb VARBIT(8),
    c1 CHAR
);
