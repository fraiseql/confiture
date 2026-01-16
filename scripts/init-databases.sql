-- ============================================================================
-- Confiture Database Initialization Script
--
-- Creates test databases and initializes them with required extensions and
-- default settings for Confiture migration testing framework.
--
-- This script is automatically executed by docker-compose at startup.
-- ============================================================================

-- Set default client encoding
SET client_encoding = 'UTF8';
SET default_transaction_isolation = 'READ COMMITTED';
SET default_transaction_deferrable = off;
SET default_transaction_read_only = off;
SET DateStyle = 'ISO, MDY';
SET TimeZone = 'UTC';

-- ============================================================================
-- CREATE TEST DATABASES
-- ============================================================================

-- Primary test database
CREATE DATABASE confiture_test
  ENCODING = 'UTF8'
  LOCALE = 'C'
  TEMPLATE = template0
  CONNECTION LIMIT = -1;

COMMENT ON DATABASE confiture_test IS 'Primary test database for Confiture migration testing';

-- Source database for sync testing
CREATE DATABASE confiture_source_test
  ENCODING = 'UTF8'
  LOCALE = 'C'
  TEMPLATE = template0
  CONNECTION LIMIT = -1;

COMMENT ON DATABASE confiture_source_test IS 'Source database for production sync testing';

-- Target database for sync testing
CREATE DATABASE confiture_target_test
  ENCODING = 'UTF8'
  LOCALE = 'C'
  TEMPLATE = template0
  CONNECTION LIMIT = -1;

COMMENT ON DATABASE confiture_target_test IS 'Target database for production sync testing';

-- ============================================================================
-- GRANT PERMISSIONS TO CONFITURE USER
-- ============================================================================

-- Grant connect and usage on all test databases
ALTER DEFAULT PRIVILEGES FOR USER postgres IN SCHEMA public GRANT ALL ON TABLES TO confiture;
ALTER DEFAULT PRIVILEGES FOR USER postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO confiture;
ALTER DEFAULT PRIVILEGES FOR USER postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO confiture;

GRANT CONNECT ON DATABASE confiture_test TO confiture;
GRANT CONNECT ON DATABASE confiture_source_test TO confiture;
GRANT CONNECT ON DATABASE confiture_target_test TO confiture;

-- Allow user to create objects in public schema
GRANT USAGE ON SCHEMA public TO confiture;
GRANT CREATE ON SCHEMA public TO confiture;

-- ============================================================================
-- CONFIGURE EXTENSIONS IN PRIMARY DATABASE
-- ============================================================================

-- Connect to primary test database
\c confiture_test

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"
  WITH SCHEMA public;

COMMENT ON EXTENSION "uuid-ossp" IS 'UUID generation functions';

CREATE EXTENSION IF NOT EXISTS "pg_trgm"
  WITH SCHEMA public;

COMMENT ON EXTENSION "pg_trgm" IS 'Text search similarity support';

-- Grant extension usage to confiture user
GRANT USAGE ON SCHEMA public TO confiture;

-- ============================================================================
-- CONFIGURE EXTENSIONS IN SOURCE DATABASE
-- ============================================================================

\c confiture_source_test

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS "pg_trgm" WITH SCHEMA public;

-- ============================================================================
-- CONFIGURE EXTENSIONS IN TARGET DATABASE
-- ============================================================================

\c confiture_target_test

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS "pg_trgm" WITH SCHEMA public;

-- ============================================================================
-- ENABLE PERFORMANCE FEATURES
-- ============================================================================

-- Return to primary database for final configuration
\c confiture_test

-- Enable JIT compilation for better performance (if available)
ALTER SYSTEM SET jit = on;
ALTER SYSTEM SET jit_above_cost = 100000;
ALTER SYSTEM SET jit_inline_above_cost = 500000;
ALTER SYSTEM SET jit_optimize_above_cost = 500000;

-- Optimize for test workloads (medium-sized datasets)
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET work_mem = '64MB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';

-- Enable connection pooling features
ALTER SYSTEM SET max_connections = 200;
ALTER SYSTEM SET max_prepared_transactions = 100;

-- Performance monitoring
ALTER SYSTEM SET log_min_duration_statement = -1;
ALTER SYSTEM SET log_checkpoints = on;
ALTER SYSTEM SET log_connections = on;
ALTER SYSTEM SET log_disconnections = on;

-- ==========================================================================
-- COMPLETION
-- ============================================================================

-- Create admin note
\echo ''
\echo '============================================================================'
\echo 'Confiture Database Initialization Complete'
\echo '============================================================================'
\echo ''
\echo 'Databases created:'
\echo '  • confiture_test            (Primary test database)'
\echo '  • confiture_source_test     (Source database for sync tests)'
\echo '  • confiture_target_test     (Target database for sync tests)'
\echo ''
\echo 'Extensions enabled (all databases):'
\echo '  • uuid-ossp     (UUID generation functions)'
\echo '  • pg_trgm       (Text search similarity)'
\echo ''
\echo 'User permissions:'
\echo '  • confiture user has CONNECT and CREATE permissions'
\echo '  • Full schema access for testing'
\echo ''
\echo 'Next steps:'
\echo '  1. Run tests: uv run pytest tests/'
\echo '  2. Monitor: docker-compose logs postgres'
\echo '  3. Admin UI: http://localhost:5050 (if pgadmin enabled)'
\echo ''
\echo '============================================================================'
\echo ''
