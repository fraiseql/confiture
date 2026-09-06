-- PostgreSQL Extensions
-- Loaded first to make functions available to later files

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable GiST index support for timestamp ranges and geometric types
CREATE EXTENSION IF NOT EXISTS "btree_gist";

-- Enable trigram similarity search (for fuzzy text matching)
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Enable cryptographic functions (for secure tokens)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Extensions loaded successfully
-- Next: 00_common/roles.sql (production only)
-- Then: 10_tables/ will use uuid_generate_v4() and gen_random_uuid()
