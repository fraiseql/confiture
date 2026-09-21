-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS users (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL,
    display_name TEXT NOT NULL,
    bio TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (email)
);

-- WARNING: no SQL derived for: ADD EXTENSION btree_gist. Edit this file before deploying.

-- WARNING: no SQL derived for: ADD EXTENSION uuid-ossp. Edit this file before deploying.
