-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS comments (
    id BIGINT NOT NULL,
    pk_comment UUID NOT NULL DEFAULT uuid_generate_v4(),
    post_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    UNIQUE (pk_comment)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS posts (
    id BIGINT NOT NULL,
    pk_post UUID NOT NULL DEFAULT uuid_generate_v4(),
    slug TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    UNIQUE (pk_post),
    UNIQUE (slug)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS users (
    id BIGINT NOT NULL,
    pk_user UUID NOT NULL DEFAULT uuid_generate_v4(),
    slug TEXT NOT NULL,
    username TEXT NOT NULL,
    email TEXT NOT NULL,
    bio TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (pk_user),
    UNIQUE (slug),
    UNIQUE (username),
    UNIQUE (email)
);

-- WARNING: no SQL derived for: ADD EXTENSION uuid-ossp. Edit this file before deploying.
