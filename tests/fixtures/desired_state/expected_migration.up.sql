-- Migration: init_from_spec
-- Version: 20260101000000

CREATE TABLE IF NOT EXISTS tb_post (
    id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    score DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS tb_user (
    id INTEGER NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT,
    is_active BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
