-- PostgreSQL extensions for blog application

-- UUID generation (required for pk_ fields)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Optional extensions (uncomment as needed):
-- CREATE EXTENSION IF NOT EXISTS "pg_trgm";        -- Text similarity
-- CREATE EXTENSION IF NOT EXISTS "pgcrypto";       -- Cryptographic functions
-- CREATE EXTENSION IF NOT EXISTS "pg_stat_statements"; -- Query statistics
