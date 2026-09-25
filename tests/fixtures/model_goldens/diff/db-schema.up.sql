-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- confiture:tier lock_risky
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
CREATE INDEX IF NOT EXISTS idx_tb_confiture_pk_confiture ON tb_confiture (pk_confiture);
CREATE INDEX IF NOT EXISTS idx_tb_confiture_slug ON tb_confiture (slug);
CREATE INDEX IF NOT EXISTS idx_tb_confiture_version ON tb_confiture (version);
CREATE INDEX IF NOT EXISTS idx_tb_confiture_applied_at ON tb_confiture (applied_at DESC);
