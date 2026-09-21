-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL NOT NULL,
    email TEXT NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    bio TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (email)
);

-- confiture:tier reversible
CREATE OR REPLACE FUNCTION update_updated_at_column() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- WARNING: no SQL derived for: ADD TRIGGER users.trigger_users_updated_at. Edit this file before deploying.
