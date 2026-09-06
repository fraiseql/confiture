-- Database Roles
-- NOTE: This file is excluded in local/CI environments (via exclude_dirs)
-- Only applied in staging and production

-- Read-only reporting role
CREATE ROLE IF NOT EXISTS confiture_readonly;
GRANT CONNECT ON DATABASE current_database() TO confiture_readonly;
GRANT USAGE ON SCHEMA public TO confiture_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO confiture_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO confiture_readonly;

-- Application role (read/write)
CREATE ROLE IF NOT EXISTS confiture_app;
GRANT CONNECT ON DATABASE current_database() TO confiture_app;
GRANT USAGE ON SCHEMA public TO confiture_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO confiture_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO confiture_app;

-- Migration role (full DDL access)
CREATE ROLE IF NOT EXISTS confiture_migration;
GRANT ALL PRIVILEGES ON DATABASE current_database() TO confiture_migration;

COMMENT ON ROLE confiture_readonly IS 'Read-only access for reporting and analytics';
COMMENT ON ROLE confiture_app IS 'Application runtime role (read/write data)';
COMMENT ON ROLE confiture_migration IS 'Migration deployment role (DDL operations)';
