-- Confiture migration tracking table
-- This table records all applied migrations

CREATE TABLE IF NOT EXISTS confiture_migrations (
    id SERIAL PRIMARY KEY,
    version VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT NOW(),
    execution_time_ms INTEGER,
    checksum VARCHAR(64),
    CONSTRAINT confiture_migrations_version_unique UNIQUE (version)
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_confiture_migrations_version
    ON confiture_migrations(version);

CREATE INDEX IF NOT EXISTS idx_confiture_migrations_applied_at
    ON confiture_migrations(applied_at DESC);

-- Comments for documentation
COMMENT ON TABLE confiture_migrations IS
    'Tracks all applied database migrations for Confiture';

COMMENT ON COLUMN confiture_migrations.version IS
    'Migration version (e.g., "001", "002")';

COMMENT ON COLUMN confiture_migrations.name IS
    'Human-readable migration name (e.g., "create_users")';

COMMENT ON COLUMN confiture_migrations.applied_at IS
    'Timestamp when migration was applied';

COMMENT ON COLUMN confiture_migrations.execution_time_ms IS
    'Migration execution time in milliseconds';

COMMENT ON COLUMN confiture_migrations.checksum IS
    'SHA256 checksum of migration file content for integrity verification';
