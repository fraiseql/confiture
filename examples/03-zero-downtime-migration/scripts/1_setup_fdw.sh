#!/bin/bash
set -euo pipefail

# Script: Setup Foreign Data Wrapper for Zero-Downtime Migration
# Purpose: Configure FDW to enable bidirectional sync between old and new schemas
# Usage: ./scripts/1_setup_fdw.sh

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check environment variables
check_env() {
    log_info "Checking environment variables..."

    if [ -z "${DATABASE_URL:-}" ]; then
        log_error "DATABASE_URL not set"
        log_info "Example: export DATABASE_URL='postgresql://user:pass@localhost:5432/myapp_production'"
        exit 1
    fi

    log_success "Environment variables OK"
}

# Test database connection
test_connection() {
    log_info "Testing database connection..."

    if ! psql "$DATABASE_URL" -c "SELECT 1" > /dev/null 2>&1; then
        log_error "Cannot connect to database"
        exit 1
    fi

    log_success "Database connection OK"
}

# Install postgres_fdw extension
install_fdw_extension() {
    log_info "Installing postgres_fdw extension..."

    psql "$DATABASE_URL" << 'EOF'
-- Install extension (requires superuser)
CREATE EXTENSION IF NOT EXISTS postgres_fdw;

-- Verify installation
SELECT extname, extversion
FROM pg_extension
WHERE extname = 'postgres_fdw';
EOF

    log_success "postgres_fdw extension installed"
}

# Create new schema for target tables
create_new_schema() {
    log_info "Creating new schema: new_users..."

    psql "$DATABASE_URL" << 'EOF'
-- Create schema if not exists
CREATE SCHEMA IF NOT EXISTS new_users;

-- Grant permissions
GRANT USAGE ON SCHEMA new_users TO CURRENT_USER;
GRANT CREATE ON SCHEMA new_users TO CURRENT_USER;

-- Verify
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name = 'new_users';
EOF

    log_success "Schema new_users created"
}

# Build new schema tables
build_new_schema() {
    log_info "Building tables in new_users schema..."

    psql "$DATABASE_URL" << 'EOF'
-- Set search path to new schema
SET search_path TO new_users;

-- Create users table with new structure
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    bio TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_first_name ON users(first_name);
CREATE INDEX IF NOT EXISTS idx_users_last_name ON users(last_name);
CREATE INDEX IF NOT EXISTS idx_users_full_name ON users(first_name, last_name);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at);

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
CREATE TRIGGER trigger_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Add comments
COMMENT ON TABLE users IS 'Users table - new schema with separate name fields';

-- Verify table creation
SELECT
    table_schema,
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema = 'new_users'
  AND table_name = 'users'
ORDER BY ordinal_position;
EOF

    log_success "New schema tables created"
}

# Create transformation functions
create_transformation_functions() {
    log_info "Creating data transformation functions..."

    psql "$DATABASE_URL" << 'EOF'
-- Function: Split full_name into first_name and last_name
CREATE OR REPLACE FUNCTION split_full_name(
    full_name TEXT,
    OUT first_name TEXT,
    OUT last_name TEXT
)
RETURNS RECORD AS $$
BEGIN
    -- Handle NULL or empty
    IF full_name IS NULL OR TRIM(full_name) = '' THEN
        first_name := '';
        last_name := '';
        RETURN;
    END IF;

    -- Trim whitespace
    full_name := TRIM(full_name);

    -- Find last space (everything before = first_name, after = last_name)
    IF POSITION(' ' IN full_name) > 0 THEN
        -- Use regexp to find last space
        first_name := SUBSTRING(full_name FROM '^(.+) [^ ]+$');
        last_name := SUBSTRING(full_name FROM '[^ ]+$');

        -- Handle NULL from regex (single name case)
        IF first_name IS NULL THEN
            first_name := full_name;
            last_name := '';
        END IF;
    ELSE
        -- No space found - single name
        first_name := full_name;
        last_name := '';
    END IF;

    -- Ensure not null
    first_name := COALESCE(TRIM(first_name), '');
    last_name := COALESCE(TRIM(last_name), '');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function: Concatenate first_name and last_name into full_name
CREATE OR REPLACE FUNCTION concat_names(
    first_name TEXT,
    last_name TEXT
)
RETURNS TEXT AS $$
BEGIN
    RETURN TRIM(CONCAT(
        COALESCE(TRIM(first_name), ''),
        ' ',
        COALESCE(TRIM(last_name), '')
    ));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Test functions
SELECT
    'John Doe' as input,
    (split_full_name('John Doe')).first_name as first_name,
    (split_full_name('John Doe')).last_name as last_name,
    concat_names(
        (split_full_name('John Doe')).first_name,
        (split_full_name('John Doe')).last_name
    ) as reconstructed;
EOF

    log_success "Transformation functions created"
}

# Create sync triggers
create_sync_triggers() {
    log_info "Creating bidirectional sync triggers..."

    # Trigger: Old → New
    psql "$DATABASE_URL" << 'EOF'
-- Trigger function: Sync from public.users to new_users.users
CREATE OR REPLACE FUNCTION sync_to_new_users()
RETURNS TRIGGER AS $$
DECLARE
    name_parts RECORD;
BEGIN
    -- Guard against infinite loops
    IF current_setting('migration.syncing', true) = 'true' THEN
        RETURN COALESCE(NEW, OLD);
    END IF;

    -- Set guard
    PERFORM set_config('migration.syncing', 'true', true);

    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        -- Split full_name
        name_parts := split_full_name(NEW.full_name);

        -- Upsert into new schema
        INSERT INTO new_users.users (
            id, email, first_name, last_name, bio, created_at, updated_at
        )
        VALUES (
            NEW.id,
            NEW.email,
            name_parts.first_name,
            name_parts.last_name,
            NEW.bio,
            NEW.created_at,
            NEW.updated_at
        )
        ON CONFLICT (id) DO UPDATE SET
            email = EXCLUDED.email,
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            bio = EXCLUDED.bio,
            updated_at = EXCLUDED.updated_at;

    ELSIF TG_OP = 'DELETE' THEN
        DELETE FROM new_users.users WHERE id = OLD.id;
        PERFORM set_config('migration.syncing', 'false', true);
        RETURN OLD;
    END IF;

    -- Clear guard
    PERFORM set_config('migration.syncing', 'false', true);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trigger_sync_to_new_users ON public.users;
CREATE TRIGGER trigger_sync_to_new_users
    AFTER INSERT OR UPDATE OR DELETE ON public.users
    FOR EACH ROW
    EXECUTE FUNCTION sync_to_new_users();

SELECT 'Trigger created: public.users → new_users.users' as status;
EOF

    # Trigger: New → Old
    psql "$DATABASE_URL" << 'EOF'
-- Trigger function: Sync from new_users.users to public.users
CREATE OR REPLACE FUNCTION sync_to_old_users()
RETURNS TRIGGER AS $$
DECLARE
    full_name_value TEXT;
BEGIN
    -- Guard against infinite loops
    IF current_setting('migration.syncing', true) = 'true' THEN
        RETURN COALESCE(NEW, OLD);
    END IF;

    -- Set guard
    PERFORM set_config('migration.syncing', 'true', true);

    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        -- Concatenate names
        full_name_value := concat_names(NEW.first_name, NEW.last_name);

        -- Upsert into old schema
        INSERT INTO public.users (
            id, email, full_name, bio, created_at, updated_at
        )
        VALUES (
            NEW.id,
            NEW.email,
            full_name_value,
            NEW.bio,
            NEW.created_at,
            NEW.updated_at
        )
        ON CONFLICT (id) DO UPDATE SET
            email = EXCLUDED.email,
            full_name = EXCLUDED.full_name,
            bio = EXCLUDED.bio,
            updated_at = EXCLUDED.updated_at;

    ELSIF TG_OP = 'DELETE' THEN
        DELETE FROM public.users WHERE id = OLD.id;
        PERFORM set_config('migration.syncing', 'false', true);
        RETURN OLD;
    END IF;

    -- Clear guard
    PERFORM set_config('migration.syncing', 'false', true);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trigger_sync_to_old_users ON new_users.users;
CREATE TRIGGER trigger_sync_to_old_users
    AFTER INSERT OR UPDATE OR DELETE ON new_users.users
    FOR EACH ROW
    EXECUTE FUNCTION sync_to_old_users();

SELECT 'Trigger created: new_users.users → public.users' as status;
EOF

    log_success "Sync triggers created"
}

# Test trigger functionality
test_triggers() {
    log_info "Testing trigger functionality..."

    psql "$DATABASE_URL" << 'EOF'
-- Test: Insert into old schema
DO $$
DECLARE
    test_id BIGINT;
BEGIN
    -- Insert test user
    INSERT INTO public.users (email, full_name, bio)
    VALUES ('trigger_test@example.com', 'Trigger Test', 'Testing triggers')
    RETURNING id INTO test_id;

    RAISE NOTICE 'Inserted test user with id: %', test_id;

    -- Verify sync to new schema
    IF EXISTS (
        SELECT 1 FROM new_users.users
        WHERE email = 'trigger_test@example.com'
          AND first_name = 'Trigger'
          AND last_name = 'Test'
    ) THEN
        RAISE NOTICE 'Old → New sync: OK';
    ELSE
        RAISE EXCEPTION 'Old → New sync: FAILED';
    END IF;

    -- Test: Update in new schema
    UPDATE new_users.users
    SET first_name = 'Updated', last_name = 'Name'
    WHERE email = 'trigger_test@example.com';

    -- Verify sync to old schema
    IF EXISTS (
        SELECT 1 FROM public.users
        WHERE email = 'trigger_test@example.com'
          AND full_name = 'Updated Name'
    ) THEN
        RAISE NOTICE 'New → Old sync: OK';
    ELSE
        RAISE EXCEPTION 'New → Old sync: FAILED';
    END IF;

    -- Cleanup
    DELETE FROM public.users WHERE email = 'trigger_test@example.com';

    RAISE NOTICE 'Trigger test completed successfully';
END $$;
EOF

    log_success "Trigger functionality verified"
}

# Create migration checkpoint table
create_checkpoint_table() {
    log_info "Creating migration checkpoint table..."

    psql "$DATABASE_URL" << 'EOF'
CREATE TABLE IF NOT EXISTS migration_checkpoint (
    id SERIAL PRIMARY KEY,
    migration_id TEXT NOT NULL,
    last_migrated_id BIGINT NOT NULL,
    rows_migrated BIGINT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_migration_checkpoint_migration_id
    ON migration_checkpoint(migration_id);

COMMENT ON TABLE migration_checkpoint IS 'Tracks progress of data migration';
EOF

    log_success "Checkpoint table created"
}

# Verify setup
verify_setup() {
    log_info "Verifying FDW setup..."

    psql "$DATABASE_URL" << 'EOF'
-- Check schemas
SELECT 'Schemas:' as check;
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name IN ('public', 'new_users')
ORDER BY schema_name;

-- Check tables
SELECT 'Tables:' as check;
SELECT table_schema, table_name, (
    SELECT COUNT(*)
    FROM information_schema.columns c
    WHERE c.table_schema = t.table_schema
      AND c.table_name = t.table_name
) as column_count
FROM information_schema.tables t
WHERE table_schema IN ('public', 'new_users')
  AND table_name = 'users'
ORDER BY table_schema;

-- Check functions
SELECT 'Functions:' as check;
SELECT routine_name
FROM information_schema.routines
WHERE routine_name IN ('split_full_name', 'concat_names', 'sync_to_new_users', 'sync_to_old_users')
ORDER BY routine_name;

-- Check triggers
SELECT 'Triggers:' as check;
SELECT trigger_schema, trigger_name, event_object_table
FROM information_schema.triggers
WHERE trigger_name IN ('trigger_sync_to_new_users', 'trigger_sync_to_old_users')
ORDER BY trigger_name;
EOF

    log_success "FDW setup verification complete"
}

# Main execution
main() {
    echo ""
    echo "======================================"
    echo "  FDW Setup for Zero-Downtime Migration"
    echo "======================================"
    echo ""

    check_env
    test_connection
    install_fdw_extension
    create_new_schema
    build_new_schema
    create_transformation_functions
    create_sync_triggers
    test_triggers
    create_checkpoint_table
    verify_setup

    echo ""
    log_success "FDW setup complete!"
    echo ""
    echo "Next steps:"
    echo "  1. Run: ./scripts/2_migrate_data.sh"
    echo "  2. Verify: ./scripts/3_verify.sh"
    echo "  3. Cutover: ./scripts/4_cutover.sh"
    echo ""
}

# Run main
main "$@"
