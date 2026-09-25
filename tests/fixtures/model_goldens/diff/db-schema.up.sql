-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS tb_confiture (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    pk_confiture BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY,
    slug TEXT NOT NULL,
    version VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    execution_time_ms INTEGER,
    checksum VARCHAR(64),
    PRIMARY KEY (id),
    UNIQUE (pk_confiture),
    UNIQUE (slug),
    UNIQUE (version)
);

-- confiture:tier additive
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
