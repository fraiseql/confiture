-- PostgreSQL Extensions for FraiseQL Blog
--
-- This file enables necessary PostgreSQL extensions for the blog application.
-- These extensions are required by FraiseQL's CQRS pattern and data structures.

-- UUID generation (for primary keys)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Advanced indexing for timestamps and ranges
CREATE EXTENSION IF NOT EXISTS "btree_gist";

-- Full-text search (for future blog post search functionality)
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Unaccent for case-insensitive search
CREATE EXTENSION IF NOT EXISTS "unaccent";

-- Comments on extensions
COMMENT ON EXTENSION "uuid-ossp" IS 'Generate UUIDs for primary keys';
COMMENT ON EXTENSION "btree_gist" IS 'GiST index support for B-tree data types';
COMMENT ON EXTENSION "pg_trgm" IS 'Trigram matching for full-text search';
COMMENT ON EXTENSION "unaccent" IS 'Remove accents from text for search';
