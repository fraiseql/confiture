-- PostgreSQL Extensions
-- Loaded first to make functions available to later files

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable GiST index support for timestamp ranges
CREATE EXTENSION IF NOT EXISTS "btree_gist";

-- Extensions loaded successfully
-- Next: 10_tables/ will use uuid_generate_v4()
