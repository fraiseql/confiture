-- Confiture migration tracking table (Trinity pattern)
-- External identifier: UUID, Internal sequence: BIGINT, Natural key: slug

CREATE TABLE IF NOT EXISTS tb_confiture (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pk_confiture BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    version VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    execution_time_ms INTEGER,
    checksum VARCHAR(64)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_tb_confiture_pk_confiture
    ON tb_confiture(pk_confiture);

CREATE INDEX IF NOT EXISTS idx_tb_confiture_slug
    ON tb_confiture(slug);

CREATE INDEX IF NOT EXISTS idx_tb_confiture_version
    ON tb_confiture(version);

CREATE INDEX IF NOT EXISTS idx_tb_confiture_applied_at
    ON tb_confiture(applied_at DESC);

-- Documentation
COMMENT ON TABLE tb_confiture IS
    'Tracks all applied database migrations for Confiture. Trinity pattern: UUID external ID, BIGINT internal sequence.';

COMMENT ON COLUMN tb_confiture.id IS
    'External UUID identifier, stable across contexts';

COMMENT ON COLUMN tb_confiture.pk_confiture IS
    'Internal sequential ID for performance optimization';

COMMENT ON COLUMN tb_confiture.slug IS
    'Human-readable reference (migration_name + timestamp)';

COMMENT ON COLUMN tb_confiture.version IS
    'Migration version prefix (e.g., "001", "002")';

COMMENT ON COLUMN tb_confiture.name IS
    'Human-readable migration name (e.g., "create_users")';

COMMENT ON COLUMN tb_confiture.applied_at IS
    'Timestamp when migration was applied';

COMMENT ON COLUMN tb_confiture.execution_time_ms IS
    'Migration execution time in milliseconds';

COMMENT ON COLUMN tb_confiture.checksum IS
    'SHA256 checksum of migration file content for integrity verification';
