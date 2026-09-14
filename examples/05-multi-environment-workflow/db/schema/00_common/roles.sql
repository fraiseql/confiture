-- Database Roles
-- NOTE: This file is excluded in local/CI environments (via exclude_dirs)
-- Only applied in staging and production
--
-- Two things PostgreSQL does not accept, and how they are written instead:
-- there is no `CREATE ROLE ... IF NOT EXISTS`, so a role is created inside a
-- guard against `pg_roles`; and `GRANT ... ON DATABASE` takes a name, not an
-- expression, so the current database is named through `format()`.

-- Read-only reporting role
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'confiture_readonly') THEN
        CREATE ROLE confiture_readonly;
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO confiture_readonly', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO confiture_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO confiture_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO confiture_readonly;

-- Application role (read/write)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'confiture_app') THEN
        CREATE ROLE confiture_app;
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO confiture_app', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO confiture_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO confiture_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO confiture_app;

-- Migration role (full DDL access)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'confiture_migration') THEN
        CREATE ROLE confiture_migration;
    END IF;
    EXECUTE format('GRANT ALL PRIVILEGES ON DATABASE %I TO confiture_migration', current_database());
END
$$;

COMMENT ON ROLE confiture_readonly IS 'Read-only access for reporting and analytics';
COMMENT ON ROLE confiture_app IS 'Application runtime role (read/write data)';
COMMENT ON ROLE confiture_migration IS 'Migration deployment role (DDL operations)';
